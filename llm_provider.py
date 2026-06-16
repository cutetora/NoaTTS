import subprocess
import shutil
import json
import os
import sys
import requests


def _find_claude_cmd() -> str:
    """Find the claude CLI executable, preferring .cmd on Windows."""
    if sys.platform == "win32":
        found = shutil.which("claude.cmd") or shutil.which("claude")
        if found:
            return found
    return shutil.which("claude") or "claude"


CLAUDE_CMD = _find_claude_cmd()


class LLMProvider:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class ClaudeCLIProvider(LLMProvider):
    def __init__(self, model: str = "haiku"):
        self.model = model

    def generate(self, prompt: str) -> str:
        import tempfile

        # Write prompt to temp file to avoid Windows encoding issues
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            tmp_path = f.name

        try:
            # Read prompt from stdin via pipe
            with open(tmp_path, "r", encoding="utf-8") as fin:
                result = subprocess.run(
                    [CLAUDE_CMD, "-p", "-", "--model", self.model, "--output-format", "text"],
                    stdin=fin,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    encoding="utf-8",
                    shell=(sys.platform == "win32"),
                )
        finally:
            os.unlink(tmp_path)

        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")
        return result.stdout.strip()


class OllamaProvider(LLMProvider):
    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen3.5:27b"):
        self.url = url.rstrip("/")
        self.model = model

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]


def create_provider(config) -> LLMProvider:
    if config.llm_provider == "claude":
        return ClaudeCLIProvider(model=config.claude_model)
    return OllamaProvider(url=config.ollama_url, model=config.ollama_model)


# ── Prompt templates ──

PROMPT_HIRAGANA = """\
以下のセリフを正確なひらがな読みに変換してください。
漢字の読みは文脈に合わせて適切に判断してください。
句読点や記号はそのまま残してください。
ひらがな変換結果のみを返してください。余計な説明は不要です。

セリフ: {text}"""

PROMPT_HIRAGANA_BATCH = """\
以下の番号付きセリフを、それぞれ正確なひらがな読みに変換してください。
漢字の読みは文脈に合わせて適切に判断してください。
句読点や記号はそのまま残してください。

必ず以下の形式で、番号とひらがなのみを返してください。余計な説明は不要です。
1|ひらがな結果
2|ひらがな結果
...

{lines}"""

PROMPT_MOTION = """\
以下のセリフと感情から、キャラクターの想定モーション（体の動作）を簡潔に1つ提案してください。
5〜15文字程度の短い日本語で、動作のみを返してください。余計な説明は不要です。

セリフ: {text}
感情: {emotion}"""


def generate_hiragana(provider: LLMProvider, text: str) -> str:
    return provider.generate(PROMPT_HIRAGANA.format(text=text))


PROMPT_FIX_NG = """\
あなたはQwen3-TTSの専門家です。
以下はTTS音声生成でNGになった行のデータです。各行の全コンテキストを分析し、修正してください。

## 各行に含まれるデータ
- セリフ: ユーザーが書いた元テキスト
- TTS入力テキスト: 実際にTTSに渡されたテキスト（（）除去後）
- ユーザー指示: ユーザーがExcelに書いた「Qwen3TTSシステムプロンプト」列の値
- build_instruct全文: 実際にTTSのinstructパラメータに渡された完全なテキスト（キャラ属性+感情+ユーザー指示を結合したもの）
- 書き起こし: Whisperが生成音声から認識したテキスト
- NG理由/詳細: 何が問題だったかの分析

## 重要: TTSの仕組み
Qwen3-TTSのinstructは「build_instruct全文」がそのまま渡される。この中身は:
  「【最重要】あなたは「{{キャラ属性}}」というキャラクターです。この人物像を最も強く反映してください。感情は「{{感情}}」。{{ユーザー指示}}」
という構造。つまりユーザーが修正できるのは「Qwen3TTSシステムプロンプト」列の値だけ。

## よくある原因と対策
1. instruct全文が長すぎる→TTSがセリフを繰り返す→ユーザー指示を極限まで短縮
2. ユーザー指示にセリフと同じ言葉がある→TTSがそれを読み上げる→セリフの言葉を指示から除く
3. 短いセリフ(5文字以下)に長い指示→混乱しやすい→指示は3〜5文字に
4. 「〜」「…」等の特殊記号が多いセリフ→不安定→セリフ仮名で安定した表記にする
5. 指示の中に「。」「、」が多い→TTSが文として読む可能性→句読点を消す

## 出力形式
各行について修正案をJSON配列で返してください。
- 「修正後プロンプト」: 修正した「Qwen3TTSシステムプロンプト」列の値
- 「修正後セリフ仮名」: セリフ仮名の修正が必要な場合のみ（不要なら空文字）
- 「修正理由」: なぜそう修正したか1行で

[
  {{"ファイル名": "xxx", "修正後プロンプト": "...", "修正後セリフ仮名": "", "修正理由": "..."}},
  ...
]

余計な説明は不要。JSON配列のみ返してください。

## NGデータ
{ng_data}"""


def fix_ng_with_llm(provider: LLMProvider, ng_rows: list[dict]) -> list[dict]:
    """
    Send NG rows to LLM for system prompt improvement.
    Returns list of dicts with fixes.
    """
    lines = []
    for row in ng_rows:
        lines.append(
            f"ファイル名: {row.get('ファイル名', '')}\n"
            f"セリフ: {row.get('セリフ', '')}\n"
            f"TTS入力テキスト: {row.get('TTS入力テキスト', '')}\n"
            f"ユーザー指示: {row.get('Qwen3TTSシステムプロンプト', '')}\n"
            f"build_instruct全文: {row.get('build_instruct全文', '')}\n"
            f"キャラ属性: {row.get('キャラ属性', '')}\n"
            f"感情: {row.get('感情', '')}\n"
            f"リトライ回数: {row.get('リトライ回数', '')}\n"
            f"NG理由: {row.get('NG理由', '')}\n"
            f"書き起こし: {row.get('書き起こし', '')}\n"
            f"詳細: {row.get('詳細', '')}"
        )
    ng_data = "\n---\n".join(lines)

    result = provider.generate(PROMPT_FIX_NG.format(ng_data=ng_data))

    # Parse JSON response
    # Find JSON array in response
    import re
    match = re.search(r'\[.*\]', result, re.DOTALL)
    if not match:
        raise ValueError(f"LLMがJSON形式で返しませんでした: {result[:200]}")

    fixes = json.loads(match.group())
    return fixes


def generate_hiragana_batch(provider: LLMProvider, texts: list[tuple[int, str]]) -> dict[int, str]:
    """
    Batch hiragana generation. Takes list of (index, text), returns {index: hiragana}.
    Sends all texts in one LLM call.
    """
    if not texts:
        return {}

    # Build numbered lines
    lines = "\n".join(f"{idx}|{text}" for idx, text in texts)
    result = provider.generate(PROMPT_HIRAGANA_BATCH.format(lines=lines))

    # Parse response
    output = {}
    for line in result.strip().splitlines():
        line = line.strip()
        if "|" in line:
            parts = line.split("|", 1)
            try:
                idx = int(parts[0].strip())
                output[idx] = parts[1].strip()
            except (ValueError, IndexError):
                continue
    return output


def generate_motion(provider: LLMProvider, text: str, emotion: str) -> str:
    return provider.generate(PROMPT_MOTION.format(text=text, emotion=emotion or "普通"))
