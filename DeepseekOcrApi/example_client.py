import requests
import time
import os


class DeepSeekOCRClient:
    def __init__(self, base_url="http://localhost:8899"):
        self.base_url = base_url
    
    def upload_pdf(self, pdf_path):
        """
        上传 PDF 文件
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        url = f"{self.base_url}/upload"
        with open(pdf_path, "rb") as f:
            files = {"file": f}
            response = requests.post(url, files=files)
        
        if response.status_code != 200:
            raise Exception(f"Upload failed: {response.text}")
        
        result = response.json()
        print(f"PDF uploaded successfully. Session ID: {result['session_id']}")
        return result["session_id"]
    
    def get_status(self, session_id):
        """
        查询处理状态
        """
        url = f"{self.base_url}/status/{session_id}"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to get status: {response.text}")
        
        return response.json()
    
    def wait_for_completion(self, session_id, check_interval=5, timeout=3600):
        """
        等待处理完成
        """
        print(f"Waiting for processing to complete...")
        start_time = time.time()
        
        while True:
            status_data = self.get_status(session_id)
            status = status_data["status"]
            print(f"Status: {status}")
            
            if status == "completed":
                print("Processing completed successfully!")
                return True
            elif status.startswith("failed"):
                print(f"Processing failed: {status}")
                return False
            
            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"Timeout after {timeout} seconds")
                return False
            
            time.sleep(check_interval)
    
    def download_result(self, session_id, output_path="results.zip"):
        """
        下载完整结果（ZIP）
        """
        url = f"{self.base_url}/result/{session_id}"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to download result: {response.text}")
        
        with open(output_path, "wb") as f:
            f.write(response.content)
        
        print(f"Results downloaded to: {output_path}")
        return output_path
    
    def get_markdown(self, session_id):
        """
        获取 Markdown 内容
        """
        url = f"{self.base_url}/result/{session_id}/markdown"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to get markdown: {response.text}")
        
        return response.json()["markdown"]
    
    def download_images(self, session_id, output_path="images.zip"):
        """
        下载所有图片
        """
        url = f"{self.base_url}/result/{session_id}/images"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to download images: {response.text}")
        
        with open(output_path, "wb") as f:
            f.write(response.content)
        
        print(f"Images downloaded to: {output_path}")
        return output_path
    
    def download_single_image(self, session_id, image_name, output_path):
        """
        下载单张图片
        """
        url = f"{self.base_url}/result/{session_id}/image/{image_name}"
        response = requests.get(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to download image: {response.text}")
        
        with open(output_path, "wb") as f:
            f.write(response.content)
        
        print(f"Image downloaded to: {output_path}")
        return output_path
    
    def delete_session(self, session_id):
        """
        删除会话
        """
        url = f"{self.base_url}/session/{session_id}"
        response = requests.delete(url)
        
        if response.status_code != 200:
            raise Exception(f"Failed to delete session: {response.text}")
        
        print(f"Session {session_id} deleted successfully")
        return True
    
    def process_pdf(self, pdf_path, output_dir=None):
        """
        完整流程：上传 -> 等待 -> 下载结果
        """
        session_id = self.upload_pdf(pdf_path)
        
        if self.wait_for_completion(session_id):
            results = {
                "session_id": session_id,
                "markdown": self.get_markdown(session_id)
            }
            
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                
                result_zip = os.path.join(output_dir, "results.zip")
                self.download_result(session_id, result_zip)
                
                images_zip = os.path.join(output_dir, "images.zip")
                self.download_images(session_id, images_zip)
                
                md_path = os.path.join(output_dir, "result.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(results["markdown"])
                
                print(f"All results saved to: {output_dir}")
            
            return results
        else:
            raise Exception("Processing failed or timed out")


if __name__ == "__main__":
    client = DeepSeekOCRClient("http://localhost:8000")
    
    # 示例使用
    pdf_file = "test.pdf"
    
    try:
        # 上传并处理 PDF
        result = client.process_pdf(pdf_file, output_dir="output")
        
        print("\n=== Markdown Content ===")
        print(result["markdown"][:500] + "..." if len(result["markdown"]) > 500 else result["markdown"])
        
    except Exception as e:
        print(f"Error: {e}")
