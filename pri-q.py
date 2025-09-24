class MaxHeap:
	def __init__(self):
		self.heap = []

	def insert(self, val):
		self.heap.append(val)
		self.heapify_up()

	def remove(self):
		if len(self.heap) == 0:
			return None
		if len(self.heap) == 1:
			return self.heap.pop()
		val = self.heap[0]
		self.heap[0] = self.heap.pop()
		self.heapify_down()
		return val

	def heapify_up(self):
		idx = len(self.heap) - 1
		while idx > 0:
			parent_idx = (idx - 1) // 2
			if self.heap[idx] > self.heap[parent_idx]:
				self.heap[idx], self.heap[parent_idx] = self.heap[parent_idx], self.heap[idx]
				idx = parent_idx
			else:
				break

	def heapify_down(self):
		idx = 0
		while idx * 2 + 1 < len(self.heap):
			left_child_idx = idx * 2 + 1
			right_child_idx = idx * 2 + 2
			if right_child_idx < len(self.heap) and self.heap[right_child_idx] > self.heap[left_child_idx]:
				largest_child_idx = right_child_idx
			else:
				largest_child_idx = left_child_idx
			if self.heap[idx] < self.heap[largest_child_idx]:
				self.heap[idx], self.heap[largest_child_idx] = self.heap[largest_child_idx], self.heap[idx]
				idx = largest_child_idx
			else:
				break


class PriorityQueue:
	def __init__(self):
		self.heap = MaxHeap()

	def insert(self, val, priority):
		self.heap.insert((priority, val))

	def remove(self):
		return self.heap.remove()[1]


# Example usage
pq = PriorityQueue()
pq.insert('Task 1', 1)
pq.insert('Task 2', 2)
pq.insert('Task 3', 3)
pq.insert('Task 4', 4)
print(pq.remove()) # Output: Task 4
print(pq.remove()) # Output: Task 3
print(pq.remove()) # Output: Task 2
print(pq.remove()) # Output: Task 1
