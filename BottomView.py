from collections import deque

class Solution:
    def bottomView(self, root):
        if not root:
            return []

        q = deque([(root, 0)])  # (node, horizontal_distance)
        hd_map = {}             # hd -> node.val

        while q:
            node, hd = q.popleft()
            # overwrite value for each hd (last seen at that hd)
            hd_map[hd] = node.val

            if node.left:
                q.append((node.left, hd - 1))
            if node.right:
                q.append((node.right, hd + 1))

        # Sort by horizontal distance
        return [hd_map[hd] for hd in sorted(hd_map.keys())]
