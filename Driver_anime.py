# Driver code
if __name__ == "__main__":
    task_list = TaskList()
    n = int(input())
    for _ in range(n):
        command = input().strip().split()

        if not command:
            continue

        op = command[0]

        if op == "A":
            # Add: A TaskID TaskName TaskType
            if len(command) != 4:
                print("Invalid input for Add operation.")
                continue
            _, task_id, name, task_type = command
            task_list.add_task(task_id, name, task_type)

        elif op == "R":
            # Remove: R TaskID
            if len(command) != 2:
                print("Invalid input for Remove operation.")
                continue
            _, task_id = command
            task_list.remove_task(task_id)

        elif op == "P":
            # Print forward
            task_list.print_forward()

        elif op == "REV":
            # Print reverse
            task_list.print_reverse()

        else:
            print("Invalid operation.")