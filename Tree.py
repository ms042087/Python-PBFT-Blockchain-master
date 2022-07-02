import math

# Structure of the node
class tnode:
	def __init__(self, data):
		self.n = data
		self.root = []

# Function to print the
# N-ary tree graphically
def printNTree(x,flag,depth,isLast,result,prev):
#	print(flag)
	# Condition when node is None
	if x == None:
		return
	
	# Loop to print the depths of the
	# current node
	'''
	for i in range(1, depth):
#		print("ENTER")
		# Condition when the depth
		# is exploring
		if flag[i]:
			print("| ","", "", "", end = "")
		
		# Otherwise print
		# the blank spaces
		else:
			print(" ", "", "", "", end = "")
	'''
	# Condition when the current
	# node is the root node
	if depth == 0:
		result.append((x.n,0,0))
		#print(x.n)
	
	# Condition when the node is
	# the last node of
	# the exploring depth
	elif isLast:
		###print("+---", x.n)
		result.append((x.n,prev,depth))
		
		# No more childrens turn it
		# to the non-exploring depth
		flag[depth] = False
	else:
#		print(flag, depth)
		###print("+---", x.n)
		result.append((x.n,prev,depth))

	it = 0
	for i in x.root:
		it+=1
		# Recursive call for the
		# children nodes
		printNTree(i, flag, depth + 1, it == (len(x.root) - 1),result,x.n)
	flag[depth] = True
	return(result)

tree = tnode(0)

def reassignNode(maxLevel,l):
	global tree
	if maxLevel==1:
		tree.root.pop()
		tree.root.pop()
		tree.root[0].root.append(tnode(5))
		tree.root[0].root.append(tnode(6))
		tree.root[0].root.append(tnode(7))
	elif maxLevel==2:
		if l==1:
			tree.root[0].root.pop()
			tree.root[0].root.pop()
			tree.root[1].root.append(tnode(8))
			tree.root[1].root.append(tnode(9))
		elif l==2:
			tree.root[0].root.pop()
			tree.root[1].root.pop()
			tree.root[2].root.append(tnode(11))
			tree.root[2].root.append(tnode(12))
		elif l==3:
			tree.root[0].root.pop()
			tree.root[1].root.pop()
			tree.root[3].root.append(tnode(14))
			tree.root[3].root.append(tnode(15))	
	elif maxLevel==3:
		if l==0:
			tree.root[0].root.pop()
			tree.root[0].root.pop()
			tree.root[0].root[0].root.append(tnode(17))
			tree.root[0].root[0].root.append(tnode(18))
			tree.root[0].root[0].root.append(tnode(19))
		if l==1:
			tree.root[0].root[0].root.pop()
			tree.root[0].root[0].root.pop()
			tree.root[0].root[1].root.append(tnode(17+3*l))
			tree.root[0].root[1].root.append(tnode(18+3*l))
			tree.root[0].root[1].root.append(tnode(19+3*l))
		if l>=2:
			result = l+4
			levelOneResult = math.ceil((result-3)/4)-1
			levelTwoResult = result-4-3*levelOneResult-1
			if result in [12,15]:
				levelTwoResult = levelTwoResult+1 
			tree.root[0].root[0].root.pop()
			tree.root[0].root[1].root.pop()
			#print(l,levelOneResult,levelTwoResult)
			tree.root[levelOneResult].root[levelTwoResult].root.append(tnode(17+3*l))
			tree.root[levelOneResult].root[levelTwoResult].root.append(tnode(18+3*l))
			tree.root[levelOneResult].root[levelTwoResult].root.append(tnode(19+3*l))
		
# Function to add node to the Tree
def addNode(maxNum):
	global tree
	maxLevel = math.ceil(math.log(maxNum)/math.log(4))
	
	# Belong to which part in last layer
	q = math.floor((maxNum-4**(maxLevel-1)-1)/3)
	r = (maxNum-4**(maxLevel-1)-1)%3
	
	d = 0 if maxLevel<=2 else 4**(maxLevel-2) # last layer last item
	#print(maxNum,": ",maxLevel,q,r,d)

	result = 0
	if q==0:
		result = 1+d
	elif q==1:
		if r==0:
			result = 1+d
		elif r==1:
			result = 1+d
		elif r==2:
			result = 2+d
			reassignNode(maxLevel,1)
	elif q>=2:
		if r==0:
			result = 1+d
		elif r==1:
			result = 2+d
		elif r==2:
			result = q+1+d
			reassignNode(maxLevel,q)
	if maxNum<7:
		tree.root.append(tnode(maxNum))
	elif maxNum==7:
		reassignNode(1,0)
	elif maxLevel==2:
		#print(maxNum,result,maxLevel)
		tree.root[result-1].root.append(tnode(maxNum))
	elif maxLevel==3 and maxNum<=18:
		tree.root[0].root.append(tnode(maxNum))
	elif maxNum==19:
		reassignNode(3,0)
	elif maxLevel==3 and maxNum>19 and maxNum not in [22,25,28,31,34,37,40,43,46,49,52]:
		#print(maxNum,result,maxLevel)
		#levelOneResult = math.ceil((maxNum-16)/9)-1
		#levelTwoResult = math.floor((maxNum-16-9*levelOneResult)/3)-1
		levelOneResult = math.ceil((result-3)/4)-1
		levelTwoResult = result-4-3*levelOneResult-1
		#print(levelOneResult,levelTwoResult,result)
		#print(tree.root[levelOneResult].root)
		tree.root[levelOneResult].root[levelTwoResult].root.append(tnode(maxNum))		

#	print(maxNum,maxLevel,q,r,result)
	result = printNTree(tree, [True]*(maxNum+1), 0, False,[],0)
	result.sort(key=lambda x:x[0]) 
	#print(result)
	return(result)
#	print("#######################################################")
#	print("printed",tree.root)

#for i in range (1,17):
#	addNode(1, i)
def calculuate_topology(n):
	global tree
	for i in range (1,n):
		result=addNode(i)
	tree = tnode(0)
	return result

def calculuate_parent(n,max_node):
	'''
	calculate_parent(10,17)
	=> 2
	'''
	global tree
	for i in range (1,max_node):
		topo=addNode(i)
	tree = tnode(0)
	result = 0
	for i in topo:
		if i[0]==n:
			result=i[1]
	return result

def calculuate_child(n,max_node):
	'''
	calculate_child(2,17)
	=> [8,9,10]
	'''
	global tree
	for i in range (1,max_node):
		topo=addNode(i)
	tree = tnode(0)
	result = []
	for i in topo:
		if i[1]==n:
			result.append(i[0])
	return result

def calculuate_view_node_count(n,max_node):

	parent_node = calculuate_parent(n,max_node)
	child_nodes = calculuate_child(parent_node,max_node)
	number_of_child = len(child_nodes) if n<5 else len(child_nodes)+1
	return number_of_child

def calculate_other_nodes_in_sub_byzantine_group(n,max_node):
	parent_node = calculuate_parent(n,max_node)
	child_nodes = calculuate_child(parent_node,max_node)
	child_nodes.remove(n)
	if n<5 and 0 in child_nodes:
		child_nodes.remove(0)
	child_nodes.append(parent_node)
	if n==0 and 0 in child_nodes:
		child_nodes.remove(0)
	return child_nodes

def calculate_primary_byzantine_nodes(n,max_node):
	parent_node = calculuate_parent(n,max_node)
	child_nodes = calculuate_child(parent_node,max_node)
	if n<5 and 0 in child_nodes:
		child_nodes.remove(0)
	child_nodes.append(parent_node)
	return child_nodes

def calculate_secondary_byzantine_nodes(n,max_node):
	child_nodes = calculuate_child(n,max_node)
	if n<5 and 0 in child_nodes:
		child_nodes.remove(0)
	return child_nodes

def isLeafNode(n,max_node):
	return calculuate_child(n,max_node)==[]

#calculuate_topology(60)