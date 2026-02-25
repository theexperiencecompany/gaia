"""
Detailed breakdown of app code in the handler bundle.
Groups by directory/feature to show where the size is coming from.
"""

import re
from collections import defaultdict
from pathlib import Path

handler_path = Path(".open-next/server-functions/default/apps/web/handler.mjs")
text = handler_path.read_text(errors="ignore")

pattern = re.compile(
    r'(?:__commonJS|__esm)\(\{["\']([^"\']+\.(?:js|mjs|cjs|ts|tsx))["\']'
)

matches = list(pattern.finditer(text))

module_sizes = []
for i in range(len(matches)):
    path_str = matches[i].group(1)
    start = matches[i].start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
    module_sizes.append((path_str, end - start))

# Show top 30 individual files
print(f"\n{'='*70}")
print("TOP 30 LARGEST INDIVIDUAL FILES")
print(f"{'='*70}")
print(f"\n{'File':<80} {'KiB':>8}")
print("-" * 90)
for path_str, size in sorted(module_sizes, key=lambda x: x[1], reverse=True)[:30]:
    short = path_str[-78:] if len(path_str) > 78 else path_str
    print(f"{short:<80} {size/1024:>8.1f}")

# Group by directory (2 levels deep from meaningful root)
dir_sizes = defaultdict(int)
for path_str, size in module_sizes:
    # Simplify path
    path_str = re.sub(r'^\.open-next/server-functions/default/apps/web/', '', path_str)
    path_str = re.sub(r'^\.open-next/', '[open-next]/', path_str)

    # Skip node_modules
    if 'node_modules/' in path_str:
        m = re.search(r'node_modules/((?:@[\w.-]+/)?[\w.-]+)', path_str)
        dir_sizes[f"node_modules/{m.group(1)}"] += size if m else 0
        continue

    parts = path_str.split('/')
    # Group by first 2-3 meaningful segments
    if len(parts) >= 3:
        key = '/'.join(parts[:3])
    elif len(parts) >= 2:
        key = '/'.join(parts[:2])
    else:
        key = parts[0]
    dir_sizes[key] += size

print(f"\n{'='*70}")
print("SIZE BY DIRECTORY")
print(f"{'='*70}")
print(f"\n{'Directory':<60} {'KiB':>8}  {'%':>5}")
print("-" * 77)
total = sum(dir_sizes.values())
for d, size in sorted(dir_sizes.items(), key=lambda x: x[1], reverse=True)[:30]:
    print(f"{d:<60} {size/1024:>8.1f}  {size/total*100:>5.1f}")
