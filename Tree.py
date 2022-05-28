# Python3 implementation to print N-ary Tree graphically
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
	
	# Condition when the current
	# node is the root node
	if depth == 0:
#		print("DEPTH0")
		result.append((x.n,0,0))
		print(x.n)
	
	# Condition when the node is
	# the last node of
	# the exploring depth
	elif isLast:
#		print("ISLAST")
		print("+---", x.n)
		result.append((x.n,prev,depth))
		
		# No more childrens turn it
		# to the non-exploring depth
		flag[depth] = False
	else:
#		print("ELSE")
#		print(flag, depth)
		print("+---", x.n)
		
		result.append((x.n,prev,depth))

	it = 0
	for i in x.root:
		it+=1
#		print("LEN",len(x.root),x.n,i.n,depth)
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

# Function to add node to the Tree
def addNode(nodeNum, maxNum):
	global tree
	maxLevel = math.ceil(math.log(maxNum)/math.log(4))
	
	q = math.floor((maxNum-4**(maxLevel-1)-1)/3)
	r = (maxNum-4**(maxLevel-1)-1)%3
	
	d = 0 if maxLevel<=2 else 4**(maxLevel-2)

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
			reassignNode(2,1)
	elif q>=2:
		if r==0:
			result = 1+d
		elif r==1:
			result = 2+d
		elif r==2:
			result = q+1+d
			reassignNode(2,q)
	if maxNum<7:
		tree.root.append(tnode(maxNum))
	elif maxNum==7:
		reassignNode(1,0)
	elif maxNum>7:
#		print("XXXXXX",tree.root[result-1].n)
		tree.root[result-1].root.append(tnode(maxNum))

#	print(maxNum,maxLevel,q,r,result)
	result = printNTree(tree, [True]*(maxNum+1), 0, False,[],0)
	result.sort(key=lambda x:x[0]) 
	return(result)
#	print("#######################################################")
#	print("printed",tree.root)

#for i in range (1,17):
#	addNode(1, i)
def calculuate_topology(n):
	for i in range (1,n):
		result=addNode(1, i)
	return result



