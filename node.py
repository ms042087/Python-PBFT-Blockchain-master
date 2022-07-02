#! /usr/bin/env python3
import logging, traceback
import argparse
import yaml
import time
from random import random, randint
from collections import Counter
import json
import sys

import asyncio
import aiohttp
from aiohttp import web

import hashlib

from Tree import *

VIEW_SET_INTERVAL = 10
TOTAL_NODE_COUNT = 17

def find_host(i):
    if i in [0,1,5,6,7]:
        host = "192.168.0.178"
    elif i in [2,8,9,10]:
        host = "192.168.0.189"
    elif i in [3,11,12,13]:
        host = "192.168.0.182"
    else:
        host = "192.168.0.193"
    return host
class View:
    def __init__(self, view_number, num_nodes):
        self._view_number = view_number
        self._num_nodes = num_nodes
        self._leader = view_number % num_nodes
        # Minimum interval to set the view number
        self._min_set_interval = VIEW_SET_INTERVAL
        self._last_set_time = time.time()

    # To encode to json
    def get_view(self):
        return self._view_number 

    # Recover from json data.
    def set_view(self, view):
        '''
        Retrun True if successfully update view number
        return False otherwise.
        '''
        if time.time() - self._last_set_time < self._min_set_interval:
            return False
        self._last_set_time = time.time()
        self._view_number = view
        self._leader = view % self._num_nodes
        return True

    def get_leader(self):
        return self._leader

class Status:
    '''
    Record the state for every slot.
    '''
    PREPARE = 'prepare'
    COMMIT = 'commit'
    REPLY = "reply"

    def __init__(self, f):
        self.f = f
        self.request = 0
        self.prepare_msgs = {}     
        self.prepare_certificate = None # proposal
        self.commit_msgs = {}
        # Only means receive more than 2f + 1 commit message,
        # but can not commit if there are any bubbles previously.
        self.commit_certificate = None # proposal

        # Set it to True only after commit
        self.is_committed = False
    
    class Certificate:
        def __init__(self, view, proposal = 0):
            '''
            input:
                view: object of class View
                proposal: proposal in json_data(dict)
            '''
            self._view = view
            self._proposal = proposal

        def to_dict(self):
            '''
            Convert the Certificate to dictionary
            '''
            return {
                'view': self._view.get_view(),
                'proposal': self._proposal
            }

        def dumps_from_dict(self, dictionary):
            '''
            Update the view from the form after self.to_dict
            input:
                dictionay = {
                    'view': self._view.get_view(),
                    'proposal': self._proposal
                }
            '''
            self._view.set_view(dictionary['view'])
            self._proposal = dictionary['proposal']
        def get_proposal(self):
            return self._proposal


    class SequenceElement:
        def __init__(self, proposal):
            self.proposal = proposal
            self.from_nodes = set([])

    def _update_sequence(self, msg_type, view, proposal, from_node):
        '''
        Update the record in the status by message type
        input:
            msg_type: Status.PREPARE or Status.COMMIT
            view: View object of self._follow_view
            proposal: proposal in json_data
            from_node: The node send given the message.
        '''

        # The key need to include hash(proposal) in case get different 
        # preposals from BFT nodes. Need sort key in json.dumps to make 
        # sure getting the same string. Use hashlib so that we got same 
        # hash everytime.
        hash_object = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode())
        key = (view.get_view(), hash_object.digest())
        if msg_type == Status.PREPARE:
            if key not in self.prepare_msgs:
                self.prepare_msgs[key] = self.SequenceElement(proposal)
            self.prepare_msgs[key].from_nodes.add(from_node)
        elif msg_type == Status.COMMIT:
            if key not in self.commit_msgs:
                self.commit_msgs[key] = self.SequenceElement(proposal)
            self.commit_msgs[key].from_nodes.add(from_node)

    def _check_majority(self, msg_type):
        '''
        Check if receive more than 2f + 1 given type message in the same view.
        input:
            msg_type: self.PREPARE or self.COMMIT
        '''
        if msg_type == Status.PREPARE:
            if self.prepare_certificate:
                return True
            for key in self.prepare_msgs:
                if len(self.prepare_msgs[key].from_nodes)>= 3: #2 * self.f + 1:
                    return True
            return False

        if msg_type == Status.COMMIT:
            if self.commit_certificate:
                return True
            for key in self.commit_msgs:
                if len(self.commit_msgs[key].from_nodes) >= 3: #2 * self.f + 1
                    return True
            return False 

class CheckPoint:
    '''
    Record all the status of the checkpoint for given PBFTHandler.
    '''
    RECEIVE_CKPT_VOTE = 'receive_ckpt_vote'
    def __init__(self, checkpoint_interval, nodes, f, node_index, 
            lose_rate = 0, network_timeout = 10):
        self._checkpoint_interval = checkpoint_interval
        self._nodes = nodes
        self._f = f
        self._node_index = node_index
        self._loss_rate = lose_rate
        self._log = logging.getLogger(__name__) 
        # Next slot of the given globally accepted checkpoint.
        # For example, the current checkpoint record until slot 99
        # next_slot = 100
        self.next_slot = 0
        # Globally accepted checkpoint
        self.checkpoint = []
        # Use the hash of the checkpoint to record receive votes for given ckpt.
        self._received_votes_by_ckpt = {} 
        self._session = None
        self._network_timeout = network_timeout

        self._log.info("---> %d: Create checkpoint.", self._node_index)

    # Class to record the status of received checkpoints
    class ReceiveVotes:
        def __init__(self, ckpt, next_slot):
            self.from_nodes = set([])
            self.checkpoint = ckpt
            self.next_slot = next_slot

    def get_commit_upperbound(self):
        '''
        Return the upperbound that could commit 
        (return upperbound = true upperbound + 1)
        '''
        return self.next_slot + 2 * self._checkpoint_interval

    def _hash_ckpt(self, ckpt):
        '''
        input: 
            ckpt: the checkpoint
        output:
            The hash of the input checkpoint in the format of 
            binary string.
        '''
        hash_object = hashlib.sha256(json.dumps(ckpt, sort_keys=True).encode())
        return hash_object.digest()  


    async def receive_vote(self, ckpt_vote):
        '''
        Trigger when PBFTHandler receive checkpoint votes.
        First, we update the checkpoint status. Second, 
        update the checkpoint if more than 2f + 1 node 
        agree with the given checkpoint.
        input: 
            ckpt_vote = {
                'node_index': self._node_index
                'next_slot': self._next_slot + self._checkpoint_interval
                'ckpt': json.dumps(ckpt)
                'type': 'vote'
            }
        '''
        self._log.debug("---> %d: Receive checkpoint votes", self._node_index)
        ckpt = json.loads(ckpt_vote['ckpt'])
        next_slot = ckpt_vote['next_slot']
        from_node = ckpt_vote['node_index']

        hash_ckpt = self._hash_ckpt(ckpt)
        if hash_ckpt not in self._received_votes_by_ckpt:
            self._received_votes_by_ckpt[hash_ckpt] = (
                CheckPoint.ReceiveVotes(ckpt, next_slot))
        status = self._received_votes_by_ckpt[hash_ckpt]
        status.from_nodes.add(from_node)
        for hash_ckpt in self._received_votes_by_ckpt:
            if (self._received_votes_by_ckpt[hash_ckpt].next_slot > self.next_slot and 
                    len(self._received_votes_by_ckpt[hash_ckpt].from_nodes) >= 2 * self._f + 1):
                self._log.info("---> %d: Update checkpoint by receiving votes", self._node_index)
                self.next_slot = self._received_votes_by_ckpt[hash_ckpt].next_slot
                self.checkpoint = self._received_votes_by_ckpt[hash_ckpt].checkpoint
               


    async def propose_vote(self, commit_decisions):
        '''
        When node the slots of committed message exceed self._next_slot 
        plus self._checkpoint_interval, propose new checkpoint and 
        broadcast to every node

        input: 
            commit_decisions: list of tuple: [((client_index, client_seq), data), ... ]

        output:
            next_slot for the new update and garbage collection of the Status object.
        '''
        proposed_checkpoint = self.checkpoint + commit_decisions
        await self._broadcast_checkpoint(proposed_checkpoint, 
            'vote', CheckPoint.RECEIVE_CKPT_VOTE)


    async def _post(self, nodes, command, json_data):
        '''
        Broadcast json_data to all node in nodes with given command.
        input:
            nodes: list of nodes
            command: action
            json_data: Data in json format.
        '''
        if not self._session:
            timeout = aiohttp.ClientTimeout(self._network_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        for i, node in enumerate(nodes):
            if random() > self._loss_rate:
                self._log.debug("make request to %d, %s", i, command)
                try:
                    _ = await self._session.post(
                        self.make_url(node, command), json=json_data)
                except Exception as e:
                    #resp_list.append((i, e))
                    self._log.error(e)
                    pass
            else:
                print("msg loss")

    @staticmethod
    def make_url(node, command):
        '''
        input: 
            node: dictionary with key of host(url) and port
            command: action
        output:
            The url to send with given node and action.
        '''
        return "http://{}:{}/{}".format(node['host'], node['port'], command)


    async def _broadcast_checkpoint(self, ckpt, msg_type, command):
        json_data = {
            'node_index': self._node_index,
            'next_slot': self.next_slot + self._checkpoint_interval,
            'ckpt': json.dumps(ckpt),
            'type': msg_type
        }
        await self._post(self._nodes, command, json_data)

    def get_ckpt_info(self):

        '''
        Get the checkpoint serialized information.Called 
        by synchronize function to get the checkpoint
        information.
        '''
        json_data = {
            'next_slot': self.next_slot,
            'ckpt': json.dumps(self.checkpoint)
        }
        return json_data

    def update_checkpoint(self, json_data):
        '''
        Update the checkpoint when input checkpoint cover 
        more slots than current.
        input: 
            json_data = {
                'next_slot': self._next_slot
                'ckpt': json.dumps(ckpt)
            }     
        '''
        self._log.debug("update_checkpoint: next_slot: %d; update_slot: %d"
            , self.next_slot, json_data['next_slot'])
        if json_data['next_slot'] > self.next_slot:
            self._log.info("---> %d: Update checkpoint by synchronization.", self._node_index)
            self.next_slot = json_data['next_slot']
            self.checkpoint = json.loads(json_data['ckpt'])
        

    async def receive_sync(sync_ckpt):
        '''
        Trigger when recieve checkpoint synchronization messages.
        input: 
            sync_ckpt = {
                'node_index': self._node_index
                'next_slot': self._next_slot + self._checkpoint_interval
                'ckpt': json.dumps(ckpt)
                'type': 'sync'
            }
        '''
        self._log.debug("receive_sync in checkpoint: current next_slot:"
            " %d; update to: %d" , self.next_slot, json_data['next_slot'])

        if sync_ckpt['next_slot'] > self._next_slot:
            self.next_slot = sync_ckpt['next_slot']
            self.checkpoint = json.loads(sync_ckpt['ckpt'])

    async def garbage_collection(self):
        '''
        Clean those ReceiveCKPT objects whose next_slot smaller
        than or equal to the current.
        '''
        deletes = []
        for hash_ckpt in self._received_votes_by_ckpt:
            if self._received_votes_by_ckpt[hash_ckpt].next_slot <= next_slot:
                deletes.append(hash_ckpt)
        for hash_ckpt in deletes:
            del self._received_votes_by_ckpt[hash_ckpt]


class ViewChangeVotes:
    """
    Record which nodes vote for the proposed view change. 
    In addition, store all the information including:
    (1)checkpoints who has the largest information(largest 
    next_slot) (2) prepare certificate with largest for each 
    slot sent from voted nodes.
    """
    def __init__(self, node_index, num_total_nodes):
        # Current node index.
        self._node_index = node_index
        # Total number of node in the system.
        self._num_total_nodes = num_total_nodes
        # Number of faults tolerand
        self._f = (self._num_total_nodes - 1) // 3
        # Record the which nodes vote for current view.
        self.from_nodes = set([])
        # The prepare_certificate with highest view for each slot
        self.prepare_certificate_by_slot = {}
        self.lastest_checkpoint = None
        self._log = logging.getLogger(__name__)

    def receive_vote(self, json_data):
        '''
        Receive the vote message and make the update:
        (1) Update the inforamtion in given vote storage - 
        prepare certificate.(2) update the node in from_nodes.
        input: 
            json_data: the json_data received by view change vote broadcast:
                {
                    "node_index": self._index,
                    "view_number": self._follow_view.get_view(),
                    "checkpoint":self._ckpt.get_ckpt_info(),
                    "prepared_certificates":self.get_prepare_certificates(),
                }
        '''
        update_view = None

        prepare_certificates = json_data["prepare_certificates"]

        self._log.debug("%d update prepare_certificate for view %d", 
            self._node_index, json_data['view_number'])

        for slot in prepare_certificates:
            prepare_certificate = Status.Certificate(View(0, self._num_total_nodes))
            prepare_certificate.dumps_from_dict(prepare_certificates[slot])
            # Keep the prepare certificate who has the largest view number
            if slot not in self.prepare_certificate_by_slot or (
                    self.prepare_certificate_by_slot[slot]._view.get_view() < (
                    prepare_certificate._view.get_view())):
                self.prepare_certificate_by_slot[slot] = prepare_certificate

        self.from_nodes.add(json_data['node_index'])


class Block:
    def __init__(self, index, transactions, timestamp, previous_hash):
        self.index          = index
        self.transactions   = transactions
        self.timestamp      = timestamp
        self.hash           = ''
        self.previous_hash  = previous_hash

    def compute_hash(self):
        """
        A function that return the hash of the block contents.
        """
        block_string = json.dumps(self.__dict__, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()
    def get_json(self):
        return json.dumps(self.__dict__ , indent=4, sort_keys=True)


class Blockchain:
    def __init__(self):
        self.commit_counter = 0
        self.length = 0
        self.chain = []
        self.create_genesis_block()

    def create_genesis_block(self):
        """
        A function to generate genesis block and appends it to
        the chain. The block has index 0, previous_hash as 0, and
        a valid hash.
        """
        genesis_block = Block(0, ["Genenesis Block"], 0, "0")
        genesis_block.hash = genesis_block.compute_hash()
        self.length += 1
        self.chain.append(genesis_block)

    # @property
    def last_block(self):
        return self.chain[-1]

    def last_block_hash(self):
        tail = self.chain[-1]
        return tail.hash

    def update_commit_counter(self):
        self.commit_counter += 1

    def add_block(self, block):
        """
        A function that adds the block to the chain after verification.
        Verification includes:
        * The previous_hash referred in the block and the hash of latest block
          in the chain match.
        """
        previous_hash = self.last_block_hash()

        if previous_hash != block.previous_hash:
            raise Exception('block.previous_hash not equal to last_block_hash')
            return

        block.hash = block.compute_hash()
        self.length += 1
        self.chain.append(block)



class PBFTHandler:
    REQUEST = 'request'
    PREPREPARE = 'preprepare'
    PREPARE = 'prepare'
    COMMIT = 'commit'
    REPLY = 'reply'
    NO_OP = 'NOP'
    RECEIVE_SYNC = 'receive_sync'
    RECEIVE_CKPT_VOTE = 'receive_ckpt_vote'
    VIEW_CHANGE_REQUEST = 'view_change_request'
    VIEW_CHANGE_VOTE = "view_change_vote"
    REQUEST_2 = 'request_2'
    PREPREPARE_2 = 'preprepare_2'
    PREPARE_2 = 'prepare_2'
    COMMIT_2 = 'commit_2'
    REPLY_2 = 'reply_2'
    NO_OP_2 = 'NOP_2'
    RECEIVE_SYNC_2 = 'receive_sync_2'
    RECEIVE_CKPT_VOTE_2 = 'receive_ckpt_vote_2'
    VIEW_CHANGE_REQUEST_2 = 'view_change_request_2'
    VIEW_CHANGE_VOTE_2 = "view_change_vote_2"


    def __init__(self, index, conf, isPrimary):
        self._nodes = conf['nodes']
        self._node_cnt = len(self._nodes)
        self._index = index
        self._isPrimary = isPrimary
        self._isSecondaryPBFTCompleted = False
        # Number of faults tolerant.
        self._f = (self._node_cnt - 1) // 3
        print("In ",index,", node_count = ", len(self._nodes))

        # leader
        self._view = View(0, self._node_cnt)
        self._next_propose_slot = 0

        self._blockchain =  Blockchain()

        # tracks if commit_decisions had been commited to blockchain
        self.committed_to_blockchain = False

        # update leader
        if isPrimary==True:
            self._is_leader = False
            self._leader = calculuate_parent(self._index,TOTAL_NODE_COUNT)
        else:
           self._is_leader = True
           self._leader = self._index

        self._json_data = {}
        # Network simulation
        self._loss_rate = conf['loss%'] / 100

        # Time configuration
        self._network_timeout = conf['misc']['network_timeout']

        # Checkpoint

        # After finishing committing self._checkpoint_interval slots,
        # trigger to propose new checkpoint.
        self._checkpoint_interval = conf['ckpt_interval']
        self._ckpt = CheckPoint(self._checkpoint_interval, self._nodes, 
            self._f, self._index, self._loss_rate, self._network_timeout)
        # Commit
        self._last_commit_slot = -1

        # The largest view either promised or accepted
        self._follow_view = View(0, self._node_cnt)
        # Restore the votes number and information for each view number
        self._view_change_votes_by_view_number = {}
        
        # Record all the status of the given slot
        # To adjust json key, slot is string integer.
        self._status_by_slot = {}

        self._sync_interval = conf['sync_interval']
 
        
        self._session = None
        self._log = logging.getLogger(__name__) 
            
    @staticmethod
    def make_url(node, command):
        '''
        input: 
            node: dictionary with key of host(url) and port
            command: action
        output:
            The url to send with given node and action.
        '''
        return "http://{}:{}/{}".format(node['host'], node['port'], command)

    async def _make_requests(self, nodes, command, json_data):
        '''
        Send json data:

        input:
            nodes: list of dictionary with key: host, port
            command: Command to execute.
            json_data: Json data.
        output:
            list of tuple: (node_index, response)

        '''
        resp_list = []
        for i, node in enumerate(nodes):
            if random() > self._loss_rate:
                if not self._session:
                    timeout = aiohttp.ClientTimeout(self._network_timeout)
                    self._session = aiohttp.ClientSession(timeout=timeout)
                self._log.debug("make request to %d, %s", i, command)
                try:
                    resp = await self._session.post(self.make_url(node, command), json=json_data)
                    resp_list.append((i, resp))
                    
                except Exception as e:
                    #resp_list.append((i, e))
                    self._log.error(e)
                    pass
            else:
                print("msg loss")
        return resp_list 

    async def _make_response(self, resp):
        '''
        Drop response by chance, via sleep for sometime.
        '''
        if random() < self._loss_rate:
            await asyncio.sleep(self._network_timeout)
        else:
            print("msg loss")
        return resp

    async def _post(self, nodes, command, json_data):
        '''
        Broadcast json_data to all node in nodes with given command.
        input:
            nodes: list of nodes
            command: action
            json_data: Data in json format.
        '''
        if not self._session:
            timeout = aiohttp.ClientTimeout(self._network_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        for i, node in enumerate(nodes):
            if random() > self._loss_rate:
                self._log.debug("make request to %d, %s", i, command)
                if command !="receive_sync":
                    print(self._index," Make request to node ", node['port']-30000, " ", command)
                try:
                    _ = await self._session.post(self.make_url(node, command), json=json_data)
                except Exception as e:
                    #resp_list.append((i, e))
                    self._log.error(e)
                    pass
            else:
                print("msg loss")

    def _legal_slot(self, slot):
        '''
        the slot is legal only when it's between upperbound and the lowerbound.
        input:
            slot: string integer direct get from the json_data proposal key.
        output:
            boolean to express the result.
        '''
        if int(slot) < self._ckpt.next_slot or int(slot) >= self._ckpt.get_commit_upperbound():
            return False
        else:
            return True

    async def preprepare(self, json_data):
        '''
        Prepare: Deal with request from the client and broadcast to other replicas.
        input:
            json_data: Json-transformed web request from client
                {
                    id: (client_id, client_seq),
                    client_url: "url string"
                    timestamp:"time"
                    data: "string"
                }

        '''

        self._json_data = json_data
        
        this_slot = str(self._next_propose_slot)
        self._next_propose_slot = int(this_slot) + 1

        self._log.info("---> %d: on preprepare, propose at slot: %d", 
            self._index, int(this_slot))

        if this_slot not in self._status_by_slot:
            self._status_by_slot[this_slot] = Status(self._f)
        self._status_by_slot[this_slot].request = json_data

        preprepare_msg = {
            'leader': self._index,
            'view': self._view.get_view(),
            'proposal': {
                this_slot: json_data
            },
            'type': 'preprepare'
        }

        await self._post(self._nodes, PBFTHandler.PREPARE, preprepare_msg)


    async def get_request(self, request):
        '''
        Handle the request from client if leader, otherwise 
        redirect to the leader.
        '''
        self._log.info("---> %d: on request", self._index)
        if self._isPrimary == True:
            if isLeafNode(self._index,TOTAL_NODE_COUNT)==False:
                print("It is not leaf node, performing secondary PBFT")
                raise web.HTTPTemporaryRedirect(self.make_url({'host': find_host(self._index), 'port': 30000+self._index}, PBFTHandler.REQUEST_2))
            else:
                print("It is a leaf node, redirecting to "+str(self._leader)+" to perform secondary PBFT")
                raise web.HTTPTemporaryRedirect(self.make_url({'host': find_host(self._index), 'port': 30000+self._leader}, PBFTHandler.REQUEST_2))

        if not self._is_leader:
            if self._leader != None:
                print("Redirecting to node "+str(self._leader))
                raise web.HTTPTemporaryRedirect(self.make_url(
                    self._nodes[self._leader], PBFTHandler.REQUEST))
            else:
                raise web.HTTPServiceUnavailable()
        else:


            json_data = await request.json()
            
            print(self._index," received request from client")

            # print("\t\t--->node"+str(self._index)+": on request :")
            # print(json_data)

            await self.preprepare(json_data)
            return web.Response()

    async def prepare(self, request):
        '''
        Once receive preprepare message from client, broadcast 
        prepare message to all replicas.

        input: 
            request: preprepare message from preprepare:
                preprepare_msg = {
                    'leader': self._index,
                    'view': self._view.get_view(),
                    'proposal': {
                        this_slot: json_data
                    }
                    'type': 'preprepare'
                }

        '''
        json_data = await request.json()
        print(self._index, "received prepare")

        if json_data['view'] < self._follow_view.get_view():
            # when receive message with view < follow_view, do nothing
            return web.Response()

        self._log.info("---> %d: receive preprepare msg from %d", 
            self._index, json_data['leader'])

        self._log.info("---> %d: on prepare", self._index)
        for slot in json_data['proposal']:

            if not self._legal_slot(slot):
                continue

            if slot not in self._status_by_slot:
                self._status_by_slot[slot] = Status(self._f)

            prepare_msg = {
                'index': self._index,
                'view': json_data['view'],
                'proposal': {
                    slot: json_data['proposal'][slot]
                },
                'type': Status.PREPARE
            }

            other_nodes = self._nodes.copy()
            other_nodes.remove({'host': find_host(self._leader), 'port': 30000+self._leader})
            leader_node = [{'host': find_host(self._leader), 'port': 30000+self._leader}]
            
            await self._post(other_nodes, PBFTHandler.COMMIT, prepare_msg)
            await self._post(leader_node, PBFTHandler.COMMIT_2, prepare_msg)

        return web.Response()

    async def commit(self, request):
        '''
        Once receive more than 2f + 1 prepare message,
        send the commit message.
        input:
            request: prepare message from prepare:
                prepare_msg = {
                    'index': self._index,
                    'view': self._n,
                    'proposal': {
                        this_slot: json_data
                    }
                    'type': 'prepare'
                }
        '''
        json_data = await request.json()
        self._log.info("---> %d: receive prepare msg from %d", 
            self._index, json_data['index'])

        # print("\t--->node "+str(self._index)+": receive prepare msg from node "+str(json_data['index']))
        # print(json_data)

        if json_data['view'] < self._follow_view.get_view():
            # when receive message with view < follow_view, do nothing
            return web.Response()


        self._log.info("---> %d: on commit", self._index)
        
        for slot in json_data['proposal']:
            if not self._legal_slot(slot):
                continue

            if slot not in self._status_by_slot:
                self._status_by_slot[slot] = Status(self._f)
            status = self._status_by_slot[slot]

            view = View(json_data['view'], self._node_cnt)

            status._update_sequence(json_data['type'], 
                view, json_data['proposal'][slot], json_data['index'])

            if status._check_majority(json_data['type']):
                status.prepare_certificate = Status.Certificate(view, 
                    json_data['proposal'][slot])
                commit_msg = {
                    'index': self._index,
                    'view': json_data['view'],
                    'proposal': {
                        slot: json_data['proposal'][slot]
                    },
                    'type': Status.COMMIT
                }
                other_nodes = self._nodes.copy()
                other_nodes.remove({'host': find_host(self._leader), 'port': 30000+self._leader})
                leader_node = [{'host': find_host(self._leader), 'port': 30000+self._leader}]
                await self._post(other_nodes, PBFTHandler.REPLY, commit_msg)
                await self._post(leader_node, PBFTHandler.REPLY_2, commit_msg)

        return web.Response()

    async def reply(self, request):
        '''
        Once receive more than 2f + 1 commit message, append the commit 
        certificate and cannot change anymore. In addition, if there is 
        no bubbles ahead, commit the given slots and update the last_commit_slot.
        input:
            request: commit message from commit:
                preprepare_msg = {
                    'index': self._index,
                    'n': self._n,
                    'proposal': {
                        this_slot: json_data
                    }
                    'type': 'commit'
                }
        '''

        json_data = await request.json()
        # print(self._index, "received commit")
        self._log.info("---> %d: on reply", self._index)
        # print("\t--->node "+str(self._index)+": on reply ")

        if json_data['view'] < self._follow_view.get_view():
            # when receive message with view < follow_view, do nothing
            return web.Response()


        self._log.info("---> %d: receive commit msg from %d", 
            self._index, json_data['index'])
        for slot in json_data['proposal']:
            if not self._legal_slot(slot):
                continue

            if slot not in self._status_by_slot:
                self._status_by_slot[slot] = Status(self._f)
            status = self._status_by_slot[slot]

            view = View(json_data['view'], self._node_cnt)

            status._update_sequence(json_data['type'], 
                view, json_data['proposal'][slot], json_data['index'])

            # Commit only when no commit certificate and got more than 2f + 1
            # commit message.
            #print(not status.commit_certificate, status._check_majority(json_data['type']))
            if not status.commit_certificate and status._check_majority(json_data['type']):

                status.commit_certificate = Status.Certificate(view, 
                    json_data['proposal'][slot])

                self._log.debug("Add commit certifiacte to slot %d", int(slot))

                # Reply only once and only when no bubble ahead
                if self._last_commit_slot == int(slot) - 1 and not status.is_committed:

                    reply_msg = {
                        'index': self._index,
                        'view': json_data['view'],
                        'proposal': json_data['proposal'][slot],
                        'type': Status.REPLY
                    }
                    status.is_committed = True
                    self._last_commit_slot += 1

                    # When commit messages fill the next checkpoint, 
                    # propose a new checkpoint.
                    if (self._last_commit_slot + 1) % self._checkpoint_interval == 0:
                        await self._ckpt.propose_vote(self.get_commit_decisions())
                        self._log.info("---> %d: Propose checkpoint with last slot: %d. "
                            "In addition, current checkpoint's next_slot is: %d", 
                            self._index, self._last_commit_slot, self._ckpt.next_slot)


                    # Commit!
                    await self._commit_action()

                    try:
                        if self._index in [0,1,2,3,4] and self._isPrimary==True:
                            print("sending reply to client")
                            await self._session.post(json_data['proposal'][slot]['client_url'], json=reply_msg)
                        elif self._index in [1,2,3,4] and self._isPrimary==False:
                            # Send request to upper layer
                            print(self._index," sending request to primary Byzantine group")
                            await self._post([{'host': find_host(calculuate_parent(self._index,TOTAL_NODE_COUNT)), 'port': 30000+calculuate_parent(self._index,TOTAL_NODE_COUNT)}], PBFTHandler.REQUEST, json_data['proposal'][slot])
                        
                    except:
                        self._log.error("Send message failed to %s", 
                            json_data['proposal'][slot]['client_url'])
                        pass
                    else:
                        print("committed")
                        self._log.info("%d reply to %s successfully!!", 
                            self._index, json_data['proposal'][slot]['client_url'])
                
        return web.Response()

    def get_commit_decisions(self):
        '''
        Get the commit decision between the next slot of the 
        current ckpt until last commit slot
        output:
            commit_decisions: list of tuple: [((client_index, client_seq), data), ... ]

        '''
        commit_decisions = []
        # print(self._ckpt.next_slot, self._last_commit_slot + 1)
        for i in range(self._ckpt.next_slot, self._last_commit_slot + 1):
            status = self._status_by_slot[str(i)]
            proposal = status.commit_certificate._proposal 

            commit_decisions.append((str(proposal['id']), proposal['data']))

        try:
            # if self._index == 3:
                # print('Node 3 is leader : ', str(self._is_leader))
            # print('Node '+str(self._index)+' is leader : ', str(self._is_leader))
            
            if not self.committed_to_blockchain and len(commit_decisions) == self._checkpoint_interval:
                self.committed_to_blockchain = True
                transactions =  commit_decisions 
                # proposal is the last proposal
                # print(proposal['timestamp'])
                try:
                    timestamp = time.asctime( time.localtime( proposal['timestamp']) )
                except Exception as e:
                    self._log.error("received invalid timestamp. replacing with current timestamp")
                    timestamp = time.asctime( time.localtime( time.time()) )
                           
                new_block=  Block(self._blockchain.length, commit_decisions, timestamp , self._blockchain.last_block_hash())
                self._blockchain.add_block(new_block)

                # if self._index == 3:
                #     print(new_block.get_json())

        except Exception as e:
            traceback.print_exc()
            print(e)

        
        # print(len(self._status_by_slot))
        # print(self._ckpt.next_slot, self._last_commit_slot + 1)
        # print(len(commit_decisions))
        # # print()
        # print()
        # print('commit_decisions')
        # print(commit_decisions)
        return commit_decisions

    async def _commit_action(self):
        '''
        Dump the current commit decisions to disk.
        '''
        # with open("~$node_{}_blockchain.dump".format(self._index), 'w') as f:
        dump_data = self._ckpt.checkpoint + self.get_commit_decisions()            
            # json.dump(dump_data, f)
        # try:
        with open("~$node_{}.blockchain".format(self._index), 'a') as f:
            # f.write(str(dump_data)+'\n\n------------\n\n')
            # print('node :' + str(self._index) +' > '+str(self._blockchain.commit_counter)+' : '+str(self._blockchain.length))
            for i in range(self._blockchain.commit_counter, self._blockchain.length):
                f.write(str(self._blockchain.chain[i].get_json())+'\n------------\n')
                self._blockchain.update_commit_counter()
        # except Exception as e:
        #     traceback.print_exc()
        #     print('for i = ' +str(i))
        #     print(e)

        # pad = ''
        # for k in range(self._index): 
        #     pad += '\t'
        # print(pad+'node :' + str(self._index) +' : '+str(self._blockchain.length))

        

    async def receive_ckpt_vote(self, request):
        '''
        Receive the message sent from CheckPoint.propose_vote()
        '''
        self._log.info("---> %d: receive checkpoint vote.", self._index)
        json_data = await request.json()


        await self._ckpt.receive_vote(json_data)
        return web.Response()

    async def receive_sync(self, request):
        '''
        Update the checkpoint and fill the bubble when receive sync messages.
        input:
            request: {
                'checkpoint': json_data = {
                    'next_slot': self._next_slot
                    'ckpt': json.dumps(ckpt)
                }
                'commit_certificates':commit_certificates
                    (Elements are commit_certificate.to_dict())
            }
        '''

        self._log.info("---> %d: on receive sync stage.", self._index)
        json_data = await request.json()

        try:
            self.committed_to_blockchain = False
        except Exception as e:
            traceback.print_exc()
            print('for i = ' +str(i))
            print(e)





        self._ckpt.update_checkpoint(json_data['checkpoint'])
        self._last_commit_slot = max(self._last_commit_slot, self._ckpt.next_slot - 1)
        # TODO: Only check bubble instead of all slots between lowerbound
        # and upperbound of the commit.

        for slot in json_data['commit_certificates']:
            # Skip those slot not qualified for update.
            if int(slot) >= self._ckpt.get_commit_upperbound() or (
                    int(slot) < self._ckpt.next_slot):
                continue

            certificate = json_data['commit_certificates'][slot]
            if slot not in self._status_by_slot:
                self._status_by_slot[slot] = Status(self._f)
                commit_certificate = Status.Certificate(View(0, self._node_cnt))
                commit_certificate.dumps_from_dict(certificate)
                self._status_by_slot[slot].commit_certificate =  commit_certificate
            elif not self._status_by_slot[slot].commit_certificate:
                commit_certificate = Status.Certificate(View(0, self._node_cnt))
                commit_certificate.dumps_from_dict(certificate)
                self._status_by_slot[slot].commit_certificate =  commit_certificate

        # Commit once the next slot of the last_commit_slot get commit certificate
        while (str(self._last_commit_slot + 1) in self._status_by_slot and 
                self._status_by_slot[str(self._last_commit_slot + 1)].commit_certificate):
            self._last_commit_slot += 1

            # When commit messages fill the next checkpoint, 
            # propose a new checkpoint.
            if (self._last_commit_slot + 1) % self._checkpoint_interval == 0:
                await self._ckpt.propose_vote(self.get_commit_decisions())

                self._log.info("---> %d: During rev_sync, Propose checkpoint with l "
                    "ast slot: %d. In addition, current checkpoint's next_slot is: %d", 
                    self._index, self._last_commit_slot, self._ckpt.next_slot)

        await self._commit_action()

        return web.Response()
        

    async def synchronize(self):
        '''
        Broadcast current checkpoint and all the commit certificate 
        between next slot of the checkpoint and commit upperbound.

        output:
            json_data = {
                'checkpoint': json_data = {
                    'next_slot': self._next_slot
                    'ckpt': json.dumps(ckpt)
                }
                'commit_certificates':commit_certificates
                    (Elements are commit_certificate.to_dict())
            }
        '''
        # TODO: Only send bubble slot message instead of all.
        while 1:
            await asyncio.sleep(self._sync_interval)
            commit_certificates = {}
            for i in range(self._ckpt.next_slot, self._ckpt.get_commit_upperbound()):
                slot = str(i)
                if (slot in self._status_by_slot) and (
                        self._status_by_slot[slot].commit_certificate):
                    status = self._status_by_slot[slot]
                    commit_certificates[slot] = status.commit_certificate.to_dict()
            json_data = {
                'checkpoint': self._ckpt.get_ckpt_info(),
                'commit_certificates':commit_certificates
            }
            await self._post(self._nodes, PBFTHandler.RECEIVE_SYNC, json_data)

    async def get_prepare_certificates(self):
        '''
        For view change, get all prepare certificates in the valid commit interval.
        output:
            prepare_certificate_by_slot: dictionary which contains the mapping between
            each slot and its prepare_certificate if exists.

        '''
        prepare_certificate_by_slot = {}
        for i in range(self._ckpt.next_slot, self._ckpt.get_commit_upperbound()):
            slot = str(i)
            if slot in self._status_by_slot:
                status = self._status_by_slot[slot]
                if status.prepare_certificate:
                    prepare_certificate_by_slot[slot] = (
                        status.prepare_certificate.to_dict())
        return prepare_certificate_by_slot

    async def _post_view_change_vote(self):
        '''
        Broadcast the view change vote messages to all the nodes. 
        View change vote messages contain current node index, 
        proposed new view number, checkpoint info, and all the 
        prepare certificate between valid slots.
        '''
        view_change_vote = {
            "node_index": self._index,
            "view_number": self._follow_view.get_view(),
            "checkpoint":self._ckpt.get_ckpt_info(),
            "prepare_certificates":await self.get_prepare_certificates(),

        }
        await self._post(self._nodes, PBFTHandler.VIEW_CHANGE_VOTE, view_change_vote)

    async def get_view_change_request(self, request):
        '''
        Get view change request from client. Broadcast the view change vote and 
        all the information needed for view change(checkpoint, prepared_certificate)
        to every replicas.
        input:
            request: view change request messages from client.
                json_data{
                    "action" : "view change"
                }
        '''

        self._log.info("---> %d: receive view change request from client.", self._index)
        json_data = await request.json()
        # Make sure the message is valid.
        if json_data['action'] != "view change":
            return web.Response()
        # Update view number by 1 and change the followed leader. In addition,
        # if receive view update message within update interval, do nothing.   
        if not self._follow_view.set_view(self._follow_view.get_view() + 1):
            return web.Response()

        self._leader = self._follow_view.get_leader()
        if self._is_leader:
            self._log.info("%d is not leader anymore. View number: %d", 
                    self._index, self._follow_view.get_view())
            self._is_leader = False

        self._log.debug("%d: vote for view change to %d.", 
            self._index, self._follow_view.get_view())

        await self._post_view_change_vote()

        return web.Response()

    async def receive_view_change_vote(self, request):
        '''
        Receive the vote message for view change. (1) Update the checkpoint 
        if receive messages has larger checkpoint. (2) Update votes message 
        (Node comes from and prepare-certificate). (3) View change if receive
        f + 1 votes (4) if receive more than 2f + 1 node and is the leader 
        of the current view, become leader and preprepare the valid slot.

        input: 
            request. After transform to json:
                json_data = {
                    "node_index": self._index,
                    "view_number": self._follow_view.get_view(),
                    "checkpoint":self._ckpt.get_ckpt_info(),
                    "prepared_certificates":self.get_prepare_certificates(),
                }
        '''

        self._log.info("%d receive view change vote.", self._index)
        json_data = await request.json()
        view_number = json_data['view_number']
        if view_number not in self._view_change_votes_by_view_number:
            self._view_change_votes_by_view_number[view_number]= (
                ViewChangeVotes(self._index, self._node_cnt))


        self._ckpt.update_checkpoint(json_data['checkpoint'])
        self._last_commit_slot = max(self._last_commit_slot, self._ckpt.next_slot - 1)

        votes = self._view_change_votes_by_view_number[view_number]

        votes.receive_vote(json_data)

        # Receive more than 2f + 1 votes. If the node is the 
        # charged leader for current view, become leader and 
        # propose preprepare for all slots.

        if len(votes.from_nodes) >= 2 * self._f + 1:

            if self._follow_view.get_leader() == self._index and not self._is_leader:

                self._log.info("%d: Change to be leader!! view_number: %d", 
                    self._index, self._follow_view.get_view())

                self._is_leader = True
                self._view.set_view(self._follow_view.get_view())
                # TODO: More efficient way to find last slot with prepare certificate.
                last_certificate_slot = max(
                    [int(slot) for slot in votes.prepare_certificate_by_slot] + [-1])

                # Update the next_slot!!
                self._next_propose_slot = last_certificate_slot + 1

                proposal_by_slot = {}
                for i in range(self._ckpt.next_slot, last_certificate_slot + 1):
                    slot = str(i)
                    if slot not in votes.prepare_certificate_by_slot:

                        self._log.debug("%d decide no_op for slot %d", 
                            self._index, int(slot))

                        proposal = {
                            'id': (-1, -1),
                            'client_url': "no_op",
                            'timestamp':"no_op",
                            'data': PBFTHandler.NO_OP
                        }
                        proposal_by_slot[slot] = proposal
                    elif not self._status_by_slot[slot].commit_certificate:
                        proposal = votes.prepare_certificate_by_slot[slot].get_proposal()
                        proposal_by_slot[slot] = proposal

                await self.fill_bubbles(proposal_by_slot)
        return web.Response()

    async def fill_bubbles(self, proposal_by_slot):
        '''
        Fill the bubble during view change. Basically, it's a 
        preprepare that assign the proposed slot instead of using 
        new slot.

        input: 
            proposal_by_slot: dictionary that keyed by slot and 
            the values are the preprepared proposals
        '''
        self._log.info("---> %d: on fill bubbles.", self._index)
        self._log.debug("Number of bubbles: %d", len(proposal_by_slot))

        bubbles = {
            'leader': self._index,
            'view': self._view.get_view(),
            'proposal': proposal_by_slot,
            'type': 'preprepare'
        }
        
        await self._post(self._nodes, PBFTHandler.PREPARE, bubbles)

    async def garbage_collection(self):
        '''
        Delete those status in self._status_by_slot if its 
        slot smaller than next slot of the checkpoint.
        '''
        await asyncio.sleep(self._sync_interval)
        delete_slots = []
        for slot in self._status_by_slot:
            if int(slot) < self._ckpt.next_slot:
                delete_slots.append(slot)
        for slot in delete_slots:
            del self._status_by_slot[slot]

        # Garbage collection for cjeckpoint.
        await self._ckpt.garbage_collection()


    async def show_blockchain(request):
        name = request.match_info.get( "Anonymous")
        text = "show blockchain here " 
        print('Node '+str(self._index)+' anything')
        return web.Response(text=text)



def logging_config(log_level=logging.ERROR, log_file=None):
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        return

    root_logger.setLevel(log_level)

    f = logging.Formatter("[%(levelname)s]%(module)s->%(funcName)s: \t %(message)s \t --- %(asctime)s")

    h = logging.StreamHandler()
    h.setFormatter(f)
    h.setLevel(log_level)
    root_logger.addHandler(h)

    if log_file:
        from logging.handlers import TimedRotatingFileHandler
        h = TimedRotatingFileHandler(log_file, when='midnight', interval=1, backupCount=7)
        h.setFormatter(f)
        h.setLevel(log_level)
        root_logger.addHandler(h)

def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

def arg_parse():
    # parse command line options
    parser = argparse.ArgumentParser(description='PBFT Node')
    parser.add_argument('-i', '--index', type=int, help='node index')
    parser.add_argument('-c', '--config', default='pbft.yaml', type=argparse.FileType('r'), help='use configuration [%(default)s]')
    parser.add_argument('-lf', '--log_to_file', default=False, type=str2bool, help='Whether to dump log messages to file, default = False')    
    args = parser.parse_args()
    return args

def conf_parse(conf_file) -> dict:
    conf = yaml.safe_load(conf_file)
    return conf

def main():
    args = arg_parse()
    if args.log_to_file:
        logging.basicConfig(filename='~$node_' + str(args.index)+'.log',
                            filemode='a', level=logging.DEBUG)
    logging_config()
    log = logging.getLogger()
    conf = conf_parse(args.config)
    log.debug(conf)



    addr = conf['nodes'][args.index]
    host = addr['host']
    port = addr['port']

    # Create two PBFT Handler, One for Primary Byzantine Group, One for Secondary Byzantine Group
    primary_byzantine_nodes= calculate_primary_byzantine_nodes(args.index,TOTAL_NODE_COUNT)
    secondary_byzantine_nodes=calculate_secondary_byzantine_nodes(args.index,TOTAL_NODE_COUNT)
    primary_conf_nodes = []
    secondary_conf_nodes = []
    for i in primary_byzantine_nodes:
        primary_conf_nodes.append({'host':find_host(i),'port':30000+i})
    for i in secondary_byzantine_nodes:
        secondary_conf_nodes.append({'host':find_host(i),'port':30000+i})
    
    primary_conf = conf.copy()
    secondary_conf = conf.copy()
    primary_conf['nodes'] = primary_conf_nodes
    secondary_conf['nodes'] = secondary_conf_nodes

    primary_pbft = PBFTHandler(args.index, primary_conf, True)
    asyncio.ensure_future(primary_pbft.synchronize())
    asyncio.ensure_future(primary_pbft.garbage_collection())
    print(args.index," formed a primary Byzantine group with ", primary_byzantine_nodes)

    app = web.Application()

    if(secondary_conf['nodes']!=[]):
        secondary_pbft = PBFTHandler(args.index, secondary_conf, False)
        asyncio.ensure_future(secondary_pbft.synchronize())
        asyncio.ensure_future(secondary_pbft.garbage_collection())
        app.add_routes([
        web.post('/' + PBFTHandler.REQUEST_2, secondary_pbft.get_request),
        web.post('/' + PBFTHandler.PREPREPARE_2, secondary_pbft.preprepare),
        web.post('/' + PBFTHandler.PREPARE_2, secondary_pbft.prepare),
        web.post('/' + PBFTHandler.COMMIT_2, secondary_pbft.commit),
        web.post('/' + PBFTHandler.REPLY_2, secondary_pbft.reply),
        web.post('/' + PBFTHandler.RECEIVE_CKPT_VOTE_2, secondary_pbft.receive_ckpt_vote),
        web.post('/' + PBFTHandler.RECEIVE_SYNC_2, secondary_pbft.receive_sync),
        web.post('/' + PBFTHandler.VIEW_CHANGE_REQUEST_2, secondary_pbft.get_view_change_request),
        web.post('/' + PBFTHandler.VIEW_CHANGE_VOTE_2, secondary_pbft.receive_view_change_vote),
        ])
        print(args.index," formed a secondary Byzantine group with ", secondary_byzantine_nodes)
    else:
        print(args.index," does not have a secondary Byzantine group")


    

    
    app.add_routes([
        web.post('/' + PBFTHandler.REQUEST, primary_pbft.get_request),
        web.post('/' + PBFTHandler.PREPREPARE, primary_pbft.preprepare),
        web.post('/' + PBFTHandler.PREPARE, primary_pbft.prepare),
        web.post('/' + PBFTHandler.COMMIT, primary_pbft.commit),
        web.post('/' + PBFTHandler.REPLY, primary_pbft.reply),
        web.post('/' + PBFTHandler.RECEIVE_CKPT_VOTE, primary_pbft.receive_ckpt_vote),
        web.post('/' + PBFTHandler.RECEIVE_SYNC, primary_pbft.receive_sync),
        web.post('/' + PBFTHandler.VIEW_CHANGE_REQUEST, primary_pbft.get_view_change_request),
        web.post('/' + PBFTHandler.VIEW_CHANGE_VOTE, primary_pbft.receive_view_change_vote),
        web.get('/'+'blockchain', primary_pbft.show_blockchain),
        ])




    web.run_app(app, host=host, port=port, access_log=None)


if __name__ == "__main__":
    main()

