import os
import io
import re
import torch
import fitz
import img2pdf
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

if torch.version.cuda == '11.8':
    os.environ["TRITON_PTXAS_PATH"] = "/usr/local/cuda-11.8/bin/ptxas"
os.environ['VLLM_USE_V1'] = '0'

from vllm import LLM, SamplingParams
from vllm.model_executor.models.registry import ModelRegistry
from transformers import AutoTokenizer

from config import (
    MODEL_PATH, PROMPT, SKIP_REPEAT, MAX_CONCURRENCY, 
    NUM_WORKERS, CROP_MODE, TEMP_DIR, GPU_MEMORY_UTILIZATION
)
from process.ngram_norepeat import NoRepeatNGramLogitsProcessor
from process.image_process import DeepseekOCR2Processor
from deepseek_ocr2 import DeepseekOCR2ForCausalLM

ModelRegistry.register_model("DeepseekOCR2ForCausalLM", DeepseekOCR2ForCausalLM)

llm = LLM(
    model=MODEL_PATH,
    hf_overrides={"architectures": ["DeepseekOCR2ForCausalLM"]},
    block_size=256,
    enforce_eager=False,
    trust_remote_code=True, 
    max_model_len=8192,
    swap_space=0,
    max_num_seqs=MAX_CONCURRENCY,
    tensor_parallel_size=1,
    gpu_memory_utilization=GPU_MEMORY_UTILIZATION,
    disable_mm_preprocessor_cache=True
)

logits_processors = [NoRepeatNGramLogitsProcessor(
    ngram_size=20, window_size=50, whitelist_token_ids={128821, 128822}
)]

sampling_params = SamplingParams(
    temperature=0.0,
    max_tokens=8192,
    logits_processors=logits_processors,
    skip_special_tokens=False,
    include_stop_str_in_output=True,
)


class PDFOCRProcessor:
    def __init__(self):
        self.prompt = PROMPT
        
    def pdf_to_images(self, pdf_path, dpi=144, image_format="PNG"):
        images = []
        pdf_document = fitz.open(pdf_path)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            Image.MAX_IMAGE_PIXELS = None
            
            if image_format.upper() == "PNG":
                img_data = pixmap.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
            else:
                img_data = pixmap.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
            
            images.append(img)
        
        pdf_document.close()
        return images
    
    def re_match(self, text):
        pattern = r'(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)'
        matches = re.findall(pattern, text, re.DOTALL)
        
        matches_image = []
        matches_other = []
        for a_match in matches:
            if '<|ref|>image<|/ref|>' in a_match[0]:
                matches_image.append(a_match[0])
            else:
                matches_other.append(a_match[0])
        return matches, matches_image, matches_other
    
    def extract_coordinates_and_label(self, ref_text, image_width, image_height):
        try:
            label_type = ref_text[1]
            cor_list = eval(ref_text[2])
        except Exception as e:
            print(e)
            return None
        
        return (label_type, cor_list)
    
    def draw_bounding_boxes(self, image, refs, jdx, output_dir):
        image_width, image_height = image.size
        img_draw = image.copy()
        draw = ImageDraw.Draw(img_draw)
        
        overlay = Image.new('RGBA', img_draw.size, (0, 0, 0, 0))
        draw2 = ImageDraw.Draw(overlay)
        
        font = ImageFont.load_default()
        img_idx = 0
        image_files = []
        
        for i, ref in enumerate(refs):
            try:
                result = self.extract_coordinates_and_label(ref, image_width, image_height)
                if result:
                    label_type, points_list = result
                    
                    color = (np.random.randint(0, 200), np.random.randint(0, 200), np.random.randint(0, 255))
                    color_a = color + (20, )
                    
                    for points in points_list:
                        x1, y1, x2, y2 = points
                        
                        x1 = int(x1 / 999 * image_width)
                        y1 = int(y1 / 999 * image_height)
                        x2 = int(x2 / 999 * image_width)
                        y2 = int(y2 / 999 * image_height)
                        
                        if label_type == 'image':
                            try:
                                cropped = image.crop((x1, y1, x2, y2))
                                img_path = os.path.join(output_dir, f"{jdx}_{img_idx}.jpg")
                                cropped.save(img_path)
                                image_files.append(f"{jdx}_{img_idx}.jpg")
                            except Exception as e:
                                print(e)
                            img_idx += 1
                        
                        try:
                            if label_type == 'title':
                                draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
                                draw2.rectangle([x1, y1, x2, y2], fill=color_a, outline=(0, 0, 0, 0), width=1)
                            else:
                                draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
                                draw2.rectangle([x1, y1, x2, y2], fill=color_a, outline=(0, 0, 0, 0), width=1)
                        except:
                            pass
            except:
                continue
        
        img_draw.paste(overlay, (0, 0), overlay)
        return img_draw, image_files
    
    def process_image_with_refs(self, image, ref_texts, jdx, output_dir):
        result_image, image_files = self.draw_bounding_boxes(image, ref_texts, jdx, output_dir)
        return result_image, image_files
    
    def process_single_image(self, image):
        prompt_in = self.prompt
        cache_item = {
            "prompt": prompt_in,
            "multi_modal_data": {
                "image": DeepseekOCR2Processor().tokenize_with_images(
                    images=[image], bos=True, eos=True, cropping=CROP_MODE
                )
            },
        }
        return cache_item
    
    def pil_to_pdf_img2pdf(self, pil_images, output_path):
        if not pil_images:
            return
        
        image_bytes_list = []
        for img in pil_images:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=95)
            img_bytes = img_buffer.getvalue()
            image_bytes_list.append(img_bytes)
        
        try:
            pdf_bytes = img2pdf.convert(image_bytes_list)
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as e:
            print(f"error: {e}")
    
    def process_pdf(self, pdf_path, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        images_dir = os.path.join(output_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)
        
        images = self.pdf_to_images(pdf_path)
        
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:  
            batch_inputs = list(tqdm(
                executor.map(self.process_single_image, images),
                total=len(images),
                desc="Pre-processed images"
            ))
        
        outputs_list = llm.generate(batch_inputs, sampling_params=sampling_params)
        
        contents_det = ''
        contents = ''
        draw_images = []
        all_image_files = []
        jdx = 0
        
        for output, img in zip(outputs_list, images):
            content = output.outputs[0].text
            
            if '<｜end▁of▁sentence｜>' in content:
                content = content.replace('<｜end▁of▁sentence｜>', '')
            else:
                if SKIP_REPEAT:
                    continue
            
            page_num = f'\n<--- Page Split --->'
            contents_det += content + f'\n{page_num}\n'
            
            image_draw = img.copy()
            matches_ref, matches_images, matches_other = self.re_match(content)
            
            result_image, image_files = self.process_image_with_refs(
                image_draw, matches_ref, jdx, images_dir
            )
            draw_images.append(result_image)
            all_image_files.extend(image_files)
            
            for idx, a_match_image in enumerate(matches_images):
                content = content.replace(
                    a_match_image, 
                    f'![](images/' + str(jdx) + '_' + str(idx) + '.jpg)\n'
                )
            
            for idx, a_match_other in enumerate(matches_other):
                content = content.replace(a_match_other, '')
                content = content.replace('\\coloneqq', ':=')
                content = content.replace('\\eqqcolon', '=:')
                content = content.replace('\n\n\n\n', '\n\n')
                content = content.replace('\n\n\n', '\n\n')
            
            contents += content + f'\n{page_num}\n'
            jdx += 1
        
        mmd_path = os.path.join(output_dir, 'result.md')
        mmd_det_path = os.path.join(output_dir, 'result_det.md')
        pdf_out_path = os.path.join(output_dir, 'result_layout.pdf')
        
        with open(mmd_det_path, 'w', encoding='utf-8') as afile:
            afile.write(contents_det)
        
        with open(mmd_path, 'w', encoding='utf-8') as afile:
            afile.write(contents)
        
        self.pil_to_pdf_img2pdf(draw_images, pdf_out_path)
        
        return {
            'markdown': contents,
            'markdown_det': contents_det,
            'images': all_image_files,
            'output_dir': output_dir
        }
