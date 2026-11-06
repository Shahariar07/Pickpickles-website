import os

BASE_DIR = 'H:/My Drive/Pickpickles website'
orders_list_path = os.path.join(BASE_DIR, 'templates', 'dashboard', 'orders_list.html')
index_path = os.path.join(BASE_DIR, 'templates', 'dashboard', 'index.html')

# 1. Update orders_list.html
with open(orders_list_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
replaced = False
while i < len(lines):
    line = lines[i]
    if 'order.created_at|date:"M d • h:i A"' in line:
        # Check if previous non-blank line was span with truncate
        # Walk back to find the span tag
        j = len(new_lines) - 1
        while j >= 0 and not new_lines[j].strip():
            j -= 1
        if j >= 0 and 'text-[10px] text-gray-400 font-medium truncate' in new_lines[j]:
            # Replace the span opening tag
            new_lines[j] = '                        <span class="inline-flex items-center gap-1 text-[10.5px] font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200 shadow-2xs whitespace-nowrap shrink-0">\n'
            # Replace the date line with icon + date
            new_lines.append('                            <i class="fa-regular fa-clock text-[9.5px] text-slate-500"></i>\n')
            new_lines.append('                            <span>{{ order.created_at|date:"M d • h:i A" }}</span>\n')
            replaced = True
            # Skip until closing </span>
            while i < len(lines) and '</span>' not in lines[i]:
                i += 1
            if i < len(lines):
                new_lines.append(lines[i]) # </span>
            i += 1
            continue
    new_lines.append(line)
    i += 1

if replaced:
    with open(orders_list_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print("SUCCESS: Updated mobile order time in orders_list.html!")
else:
    print("WARNING: Could not find target line in orders_list.html")

# 2. Update index.html
with open(index_path, 'r', encoding='utf-8') as f:
    idx_content = f.read()

idx_target = """                            <div class="text-[10px] text-gray-400 font-medium mt-0.5">
                                {{ order.created_at|date:"M d, h:i A" }}
                            </div>"""

idx_replacement = """                            <div class="inline-flex items-center gap-1 text-[10px] text-slate-700 font-bold bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 mt-1 whitespace-nowrap">
                                <i class="fa-regular fa-clock text-[9px] text-slate-500"></i>
                                <span>{{ order.created_at|date:"M d, h:i A" }}</span>
                            </div>"""

if idx_target in idx_content:
    idx_content = idx_content.replace(idx_target, idx_replacement)
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(idx_content)
    print("SUCCESS: Updated order time badge in index.html!")
else:
    print("WARNING: Could not find target in index.html, check whitespace")
