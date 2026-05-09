import requests
import time
import os
import base64

BASE_URL = "http://127.0.0.1:8899"

def test_ocr_service(pdf_file_path):
    print(f"开始测试 OCR 服务...")
    print(f"上传文件: {pdf_file_path}")
    
    try:
        upload_url = f"{BASE_URL}/upload"
        with open(pdf_file_path, "rb") as f:
            files = {"file": f}
            response = requests.post(upload_url, files=files)
            response.raise_for_status()
            session_id = response.json()["session_id"]
            print(f"上传成功! Session ID: {session_id}")
        
        status_url = f"{BASE_URL}/status/{session_id}"
        print("开始轮询处理状态...")
        
        while True:
            response = requests.get(status_url)
            response.raise_for_status()
            result = response.json()
            status = result["status"]
            
            print(f"当前状态: {status}")
            
            if status == "completed":
                print("处理完成!")
                break
            elif status.startswith("failed"):
                print(f"处理失败: {status}")
                return None
            elif status == "processing":
                print("处理中...")
            
            time.sleep(5)
        
        markdown_url = f"{BASE_URL}/result/{session_id}/markdown"
        response = requests.get(markdown_url)
        response.raise_for_status()
        markdown_content = response.json()["markdown"]
        
        markdown_file = os.path.join(current_dir, "result.md")
        with open(markdown_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"Markdown 内容已保存到: {markdown_file}")
        
        images_url = f"{BASE_URL}/result/{session_id}/images/base64"
        response = requests.get(images_url)
        response.raise_for_status()
        images_data = response.json()
        
        images_dir = os.path.join(current_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        
        print(f"\n开始下载图片...")
        for img in images_data["images"]:
            img_name = img["name"]
            img_base64 = img["base64"]
            img_path = os.path.join(images_dir, img_name)
            
            img_bytes = base64.b64decode(img_base64)
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            print(f"  - {img_name} ({img['size']} bytes)")
        
        print(f"\n所有图片已保存到: {images_dir}")
        print(f"共 {images_data['total']} 张图片")
        
        print("\n" + "="*50)
        print("Markdown 内容:")
        print("="*50)
        print(markdown_content)
        print("="*50)
        
        return markdown_content
        
    except requests.exceptions.RequestException as e:
        print(f"请求错误: {e}")
        return None
    except FileNotFoundError:
        print(f"错误: 找不到文件 {pdf_file_path}")
        return None
    except Exception as e:
        print(f"发生错误: {e}")
        return None

if __name__ == "__main__":
    import os
    current_dir = "/home/ubuntu/jiang/ragproject/deepseek-ocr/example/output"
    os.makedirs(current_dir, exist_ok=True)
    pdf_file = "/home/ubuntu/jiang/ragproject/deepseek-ocr/example/input/大纲模板：G246涵洞（通道）专项施工方案.pdf"
    test_ocr_service(pdf_file)
