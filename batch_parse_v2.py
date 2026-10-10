import json
import os
import requests
from bs4 import BeautifulSoup

print("🚀 Master Batch Parser v2 (With Solutions): Folder ki saari HTML files ko process kar raha hoon...\n")

master_dataset = []

def extract_content(html_block):
    if not html_block: 
        return {"text": "", "images": []}
    text = html_block.get_text(separator=' ', strip=True).replace('\xa0', ' ').strip()
    imgs = []
    for img in html_block.find_all("img"):
        src = img.get("data-orsrc") or img.get("src")
        if src:
            if src.startswith('/'):
                src = "https://questions.examside.com" + src
            imgs.append(src)
    return {"text": text, "images": imgs}

html_files = [f for f in os.listdir('.') if f.endswith('.html')]

if not html_files:
    print("❌ Koi bhi .html file nahi mili!")
else:
    print(f"📁 Mili hui HTML files: {html_files}\n")

for filename in html_files:
    print(f"📄 Processing: {filename}")
    try:
        with open(filename, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            
        question_boxes = soup.find_all("div", class_=lambda c: c and "question-component" in c)
        print(f"   -> Found {len(question_boxes)} questions.")
        
        for box in question_boxes:
            q_id = box.get('data-qid', '')
            q_type = box.get('data-type', '')
            
            paper_tag = box.find("div", class_="q-paper")
            paper_name = paper_tag.get_text(strip=True) if paper_tag else ""
            
            marks = "+4 / -1"
            
            q_body_div = box.find("div", class_="q-body")
            q_content = extract_content(q_body_div)
            
            options_data = []
            options_container = box.find("div", class_="options")
            if options_container:
                for opt in options_container.find_all("div", class_="option"):
                    badge = opt.find("span", class_="option-badge")
                    badge_text = badge.get_text(strip=True) if badge else ""
                    opt_content_div = opt.find("div", class_="option-content")
                    opt_content = extract_content(opt_content_div)
                    options_data.append({
                        "option_code": badge_text,
                        "text": opt_content["text"],
                        "images": opt_content["images"]
                    })
                    
            # Detailed Solution Extract karna
            solution_div = box.find("div", class_="when-answered")
            solution_content = extract_content(solution_div)
                    
            # API se direct Correct Option
            correct_answer = None
            if q_id:
                api_url = "https://questions.examside.com/api/check_answer"
                payload = {"qid": q_id, "input": None, "options": [], "timeSpent": 0}
                try:
                    res = requests.post(api_url, json=payload)
                    if res.status_code == 200:
                        correct_answer = res.json()
                except Exception as e:
                    pass

            q_data = {
                "id": q_id,
                "type": q_type,
                "paper": paper_name,
                "marks": marks,
                "question": q_content,
                "options": options_data,
                "solution": solution_content, 
                "correct_answer": correct_answer
            }
            master_dataset.append(q_data)
            
    except Exception as e:
        print(f"❌ Error in {filename}: {e}")

output_file = "full_jee_dataset_v2.json"
with open(output_file, "w", encoding="utf-8") as out:
    json.dump(master_dataset, out, indent=4, ensure_ascii=False)

print(f"\n🎉 BOOM! Total {len(master_dataset)} Questions with Solutions saved in '{output_file}'!")

