class Node:
    def __init__(self, data):
        self.data = data
        self.left = None
        self.right = None

def height(node):
    """
    Compute the height of the binary tree.
    Returns -1 if counting edges, 0 if counting nodes.
    """
    if node is None:
        return -1  # change to 0 if you want height in terms of nodes
    left_height = height(node.left)
    right_height = height(node.right)
    return max(left_height, right_height) + 1

def inorder(node):
    """In-order traversal to visualize the tree."""
    if node:
        inorder(node.left)
        print(node.data, end=" ")
        inorder(node.right)

# Example usage
if __name__ == "__main__":
    # Build a sample tree
    root = Node(50)
    root.left = Node(30)
    root.right = Node(70)
    root.left.left = Node(20)
    root.left.right = Node(40)
    root.right.left = Node(60)
    root.right.right = Node(80)

    print("In-order traversal of tree:")
    inorder(root)
    print()

    h = height(root)
    print(f"Height of the tree (edges): {h}")
