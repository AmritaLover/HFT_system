class Node:
    def __init__(self, data):
        self.data = data
        self.left = None
        self.right = None

class DLLNode:
    def __init__(self, data):
        self.data = data
        self.prev = None
        self.next = None

class Solution:
    def __init__(self):
        self.head = None
        self.tail = None

    # Extract leaf nodes and create DLL
    def extractLeaves(self, root):
        if root is None:
            return None

        # If leaf node
        if root.left is None and root.right is None:
            dll_node = DLLNode(root.data)
            if self.head is None:
                self.head = self.tail = dll_node
            else:
                self.tail.next = dll_node
                dll_node.prev = self.tail
                self.tail = dll_node
            return None  # Remove leaf from tree

        # Recur for left and right subtrees
        root.left = self.extractLeaves(root.left)
        root.right = self.extractLeaves(root.right)
        return root

    # Print DLL
    def printDLL(self):
        current = self.head
        while current:
            print(current.data, end=" <-> " if current.next else "")
            current = current.next
        print()


# Example usage
if __name__ == "__main__":
    # Binary tree
    root = Node(1)
    root.left = Node(2)
    root.right = Node(3)
    root.left.left = Node(4)
    root.left.right = Node(5)
    root.right.right = Node(6)
    root.right.left = Node(7)
    root.left.left.left = Node(8)

    sol = Solution()
    root = sol.extractLeaves(root)
    print("Doubly linked list of leaves:")
    sol.printDLL()
