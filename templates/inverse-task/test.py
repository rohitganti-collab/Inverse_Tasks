from oracle.setup import Oracle
from solution.main import solve
from solution.shortcut import solve as shortcut

oracle = Oracle()

result = solve(oracle)
shortcut_result = shortcut(oracle)

print("solve returned   :", result)
print("shortcut returned:", shortcut_result)