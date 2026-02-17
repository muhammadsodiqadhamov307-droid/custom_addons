# -*- coding: utf-8 -*-
import json
import logging
import requests
import base64
try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    HAS_GEMINI = True
except (ImportError, Exception):
    HAS_GEMINI = False

_logger = logging.getLogger(__name__)

class GeminiService:
    @staticmethod
    def process_request(api_key, text_prompt=None, media_data=None, mime_type=None):
        if not HAS_GEMINI:
            return {'error': "Serverda Google GenAI kutubxonasi o'rnatilmagan."}
        
        if not api_key:
            return {'error': "API kalit topilmadi. Tizim sozlamalarini tekshiring."}

        try:
            genai.configure(api_key=api_key)
            
            # Model Configuration
            generation_config = {
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json",
            }
            
            model = genai.GenerativeModel(
                model_name="gemini-flash-latest",
                generation_config=generation_config,
                system_instruction="""
                    Sen qurilish bo'yicha yordamchisan. 
                    Foydalanuvchi senga materiallar ro'yxatini matn, rasm yoki ovoz ko'rinishida yuboradi.
                    Sening vazifang:
                    1. Materiallarni aniqlash (nomi, miqdori, o'lchov birligi).
                    2. Faqat quyidagi JSON formatda javob qaytarish.
                    3. Hech qanday qo'shimcha so'z yozma.
                    4. O'lchov birliklari faqat bular bo'lishi shart: 'dona', 'm', 'm2', 'm3', 'kg', 'litr', 'qop', 'komplekt', 'pachka', 'rulon'.
                    5. MANTIQIY TEKSHIRUV (MUHIM): 
                       - Agar foydalanuvchi noto'g'ri birlik aytsa, uni to'g'irlash SHART.
                       - Masalan: "Reyka 10 m2" desa -> "Reyka" - "10" - "m" (chunki reyka stroykada metrlab o'lchanadi).
                       - "Kafel 5 m" desa -> "Kafel" - "5" - "m2".
                       - "Gipsokarton 5 m2" desa -> "Gipsokarton" - "5" - "dona" (yoki list). Agar m2 bolsa donaga o'girish qiyin bo'lsa m2 qoldir.
                       - "Armatura" -> "tonna" yoki "kg" yoki "metr" (vaziyatga qarab, lekin m2 bo'lmaydi).
                       - "Beton" -> "m3".
                    6. Agar miqdor aytilmasa, 1 deb ol.
                    7. Agar so'rov tushunarsiz bo'lsa, 'warnings' ga o'zbek tilida sababini yoz.
                    
                    JSON Schema:
                    {
                        "items": [
                            {
                                "name_raw": "Original name from user",
                                "name_clean": "Cleaned standardized name (Uzbek)",
                                "qty": float,
                                "uom": "dona|m|m2|m3|kg|litr|qop|komplekt|pachka|rulon|tonna"
                            }
                        ],
                        "warnings": ["Warning text if any"]
                    }
                """
            )

            # Prepare content parts
            parts = []
            if text_prompt:
                parts.append(text_prompt)
            
            if media_data and mime_type:
                # Gemini expects dict for blob
                parts.append({
                    "mime_type": mime_type,
                    "data": media_data # bytes
                })
            
            if not parts:
                return {'error': "Input yo'q."}

            response = model.generate_content(parts)
            
            # Parse JSON response
            try:
                result = json.loads(response.text)
                return result
            except json.JSONDecodeError:
                # Fallback clean extraction
                text = response.text.strip()
                if text.startswith('```json'):
                    text = text[7:-3]
                try:
                    return json.loads(text)
                except:
                    return {'error': "AI javobini o'qib bo'lmadi (JSON error).", 'raw': response.text}
                    
        except Exception as e:
            _logger.error(f"Gemini API Error: {e}")
            return {'error': f"AI Xatolik: {str(e)}"}

    @staticmethod
    def process_pricing_request(api_key, media_data, mime_type):
        """
        Extracts (product_name, price) pairs from audio/text for Snab.
        """
        if not HAS_GEMINI:
            return {'error': "Serverda Google GenAI kutubxonasi o'rnatilmagan."}
        
        if not api_key:
            return {'error': "API kalit topilmadi."}

        try:
            genai.configure(api_key=api_key)
            
            # Specialized System Instruction for Pricing
            system_instruction = """
                Sen qurilish materiali narxlovchi yordamchisan.
                Foydalanuvchi senga ovozli xabar yuboradi, unda materiallar va ularning narxlari aytiladi.
                Vazifang:
                1. Serni tinglab, material nomi va uning narxini ajratib olish.
                2. Narxni faqat raqam ko'rinishida (so'mda) olish. Agar "ming", "million" so'zlari bo'lsa, raqamga o'girish (masalan "50 ming" -> 50000).
                3. JSON formatda javob qaytarish.
                4. Agar material nomi aniq aytilmasa yoki tushunarsiz bo'lsa, tashlab ketma, imkon qadar yoz.
                
                JSON Schema:
                {
                    "items": [
                        {
                            "name": "Material nomi (masalan: Gipsokarton)",
                            "price": float (masalan: 50000)
                        }
                    ]
                }
            """
            
            generation_config = {
                "temperature": 0.1, # Low temp for precision
                "response_mime_type": "application/json",
            }
            
            model = genai.GenerativeModel(
                model_name="gemini-flash-latest", # Or gemini-1.5-flash
                generation_config=generation_config,
                system_instruction=system_instruction
            )
            
            parts = []
            if media_data and mime_type:
                parts.append({
                    "mime_type": mime_type,
                    "data": media_data
                })
            else:
                 return {'error': "Ovozli xabar topilmadi."}
                 
            response = model.generate_content(parts)
            
            try:
                result = json.loads(response.text)
                return result
            except json.JSONDecodeError:
                 # Fallback
                text = response.text.strip()
                if text.startswith('```json'): text = text[7:-3]
                try:
                    return json.loads(text)
                except:
                    return {'error': "AI javobini o'qib bo'lmadi.", 'raw': response.text}

        except Exception as e:
            _logger.error(f"Gemini Pricing Error: {str(e)}")
            return {'error': f"AI Xatolik: {str(e)}"}
