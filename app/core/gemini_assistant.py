import logging
from typing import Optional

logger = logging.getLogger("lumina.gemini")

# Support both new google-genai and legacy google-generativeai SDK
try:
    from google import genai as _genai
    _SDK = "new"
except ImportError:
    try:
        import google.generativeai as _genai  # type: ignore[no-redef]
        _SDK = "legacy"
    except ImportError:
        _genai = None
        _SDK = "none"


class GeminiAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if _SDK == "new":
            self._client = _genai.Client(api_key=api_key)
        elif _SDK == "legacy":
            _genai.configure(api_key=api_key)
            self._model = _genai.GenerativeModel("gemini-1.5-flash")
        else:
            raise ImportError("Neither google-genai nor google-generativeai is installed.")

    def analyze_disk_issue(self, disk_info: dict, scan_stats: Optional[dict] = None) -> str:
        """Send disk info to Gemini and return diagnostic text."""
        system_prompt = (
            "You are the Lumina AI Disk Assistant, a specialist in data recovery and disk forensics. "
            "Your goal is to analyze disk information and provide SAFE software-based solutions. "
            "CRITICAL RULES:\n"
            "1. NEVER suggest formatting the disk or any action that causes data loss.\n"
            "2. Focus ONLY on software repairs (e.g., SFC, CHKDSK /F, partition table repair, driver updates, file system optimization).\n"
            "3. If physical damage is suspected (e.g., IO errors, clicking), warn the user and suggest professional recovery.\n"
            "4. Be concise, professional, and helpful.\n"
            "5. Provide step-by-step instructions for the suggested tools."
        )

        disk_context = (
            f"Disk Name: {disk_info.get('name', 'Unknown')}\n"
            f"Device: {disk_info.get('device', 'Unknown')}\n"
            f"Total Size: {disk_info.get('size_gb', 0)} GB\n"
            f"Used Space: {disk_info.get('used_gb', 0)} GB\n"
        )
        if scan_stats:
            disk_context += (
                f"\nScan Results:\n"
                f"- Files found: {scan_stats.get('files_found', 0)}\n"
                f"- Error count: {scan_stats.get('errors', 0)}\n"
            )
            if scan_stats.get("last_error"):
                disk_context += f"- Last error message: {scan_stats['last_error']}\n"

        prompt = f"{system_prompt}\n\nContext:\n{disk_context}\n\nPlease analyze this disk and provide recommendations."

        try:
            if _SDK == "new":
                response = self._client.models.generate_content(
                    model="gemini-2.0-flash", contents=prompt
                )
                return response.text
            else:
                response = self._model.generate_content(prompt)
                return response.text
        except Exception as e:
            logger.error("Gemini API Error: %s", e)
            return f"Error: Unable to reach Gemini AI. {e}"
