This is an extension to Practical-Byzantine-Fault-Tolerance-PBFT implementation by CyHsiung

## ChangeLog
 * Added a Blockchain implementation
 * Replaced `MD5` hash with `SHA-256`
 * Minor Bugfix
 
 



A simple PBFT protocol over HTTP, using `python3` `asyncio/aiohttp`. This is just a proof of concept implementation.

## Run the nodes and client
Execute `run.sh` in a terminal. 
Or
Execute `run_node.sh` and `run_client.sh` in seperate terminals. 

## Send data to the blockchain network
First, execute `run_node.sh` to get the blockchain network running.

Next run a single client instance, to receive the response from the blockchain network, through the command :

`python client.py -id 0 -nm 0 &` 

Finally through the following command  a nessagege can be sent to the blockchain network :

```
curl -vLX POST --data '{ "id":"(0, 0)",
   "client_url":"http://localhost:20001/reply",
   "timestamp":"timestamp",
   "data":"data_string"}' http://localhost:30000/request
 ```
   
The `id` here is a tuple of `(client_id, seq_id)`, `client_url` is the url for sending a request to the `get_reply function()`,
`timestamp` is the current time, `data` is whatever data in string format. `http://localhost:30000/request` is the default address of the first node in the blockchain network.

Note that a new block is added to the blockchain after `ckpt_interval (default = 10)` messages are received.

## Configuration
`pbft.yaml` config file defines the default values for the blockchain network. 

## Environment
```
Python: 3.5.3
aiohttp: 3.4.4
yaml: 3.12
```
