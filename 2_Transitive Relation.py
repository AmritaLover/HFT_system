def is_transitive(relation):
    """Check if the relation is transitive"""
    for (a, b) in relation:
        for (x, y) in relation:
            if b == x and (a, y) not in relation:
                return False
    return True


def verify_equivalence_relation(relation, Set_A):
    """Verify if the relation is an equivalence relation"""
    return is_reflexive(relation, Set_A) and is_symmetric(relation) and is_transitive(relation)


# Example usage
relation = {(1, 1), (2, 2), (3, 3), (1, 2), (2, 1), (2, 3), (3, 2)}
Set_A = {1, 2, 3}

print("Is Reflexive:", is_reflexive(relation, Set_A))
print("Is Symmetric:", is_symmetric(relation))
print("Is Transitive:", is_transitive(relation))
print("Is Equivalence Relation:", verify_equivalence_relation(relation, Set_A))
