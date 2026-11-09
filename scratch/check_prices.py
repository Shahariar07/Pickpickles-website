import re, sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:/Users/Smart view/.gemini/antigravity/brain/380deae3-ee8e-455b-9adf-cf8913b27042/.system_generated/steps/3/content.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'leading-tight' in line and ('?' in line or '৳' in line or any(c.isdigit() for c in line)):
        # Look backwards for product name
        prod_name = "Unknown"
        for k in range(max(0, i-60), i):
            if '<h4' in lines[k] or '<h3' in lines[k] or '<h2' in lines[k] or 'font-bold text-slate-900' in lines[k] or 'font-display' in lines[k]:
                # clean tags
                clean = re.sub('<[^<]+?>', '', lines[k]).strip()
                if clean and len(clean) > 2 and 'OFF' not in clean and 'Fresh' not in clean:
                    prod_name = clean
            elif 'title="' in lines[k]:
                m = re.search(r'title="([^"]+)"', lines[k])
                if m:
                    prod_name = m.group(1)
            elif 'alt="' in lines[k]:
                m = re.search(r'alt="([^"]+)"', lines[k])
                if m and len(m.group(1)) > 3:
                    prod_name = m.group(1)

        # Look forward 5 lines for cut price
        context = "".join(lines[i:min(len(lines), i+6)])
        cut = re.search(r'line-through[^>]*>([^<]+)</span>', context)
        save = re.search(r'rounded[^>]*>([^<]+)</span>', context)
        curr_price = re.sub('<[^<]+?>', '', line).strip()
        cut_price = cut.group(1).strip() if cut else ''
        save_badge = save.group(1).strip() if save else ''
        print(f"Line {i+1} | Product: {prod_name:30} | Price: {curr_price:10} | Cut: {cut_price:10} | Badge: {save_badge}")
