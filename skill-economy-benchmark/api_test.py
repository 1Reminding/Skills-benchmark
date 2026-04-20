import httpx
import openai
import json
import traceback
import re

api_key="sk-nmEdDXCwUF9soc8q67DYw5GzhqalxGwptiwPQhoNUa5ZpSH0"
base_url="https://yibuapi.com/v1"
model = "gemini-3-flash-preview"   # 改成你平台实际模型名

client = openai.OpenAI(
    api_key=api_key,
    base_url=base_url,
)

def run_test(name, func):
    print("\n" + "=" * 30)
    print(name)
    print("=" * 30)
    try:
        func()
    except Exception:
        traceback.print_exc()


def extract_json_text(text: str) -> str:
    """
    兼容下面几种情况：
    1. 纯 JSON
    2. ```json ... ``` 包裹
    3. ``` ... ``` 包裹
    """
    text = text.strip()

    # 去掉 ```json ... ``` 或 ``` ... ```
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.S)
    if match:
        return match.group(1).strip()

    return text


def test_basic():
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "请只回答：OK"}
        ],
        temperature=0.2,
    )
    print(resp.choices[0].message.content)


def test_stream():
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "用中文介绍一下缓存雪崩，100字内。"}
        ],
        stream=True,
    )

    full_text = []

    for chunk in stream:
        # 某些兼容网关最后一个 chunk 可能 choices 为空
        if not getattr(chunk, "choices", None):
            continue

        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue

        content = getattr(delta, "content", None)
        if content:
            print(content, end="", flush=True)
            full_text.append(content)

    print("\n")
    print("流式输出长度：", len("".join(full_text)))


def test_json():
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    "输出一个JSON，字段只有 name 和 score，"
                    "name=alice, score=95。"
                    "不要输出 markdown，不要输出解释。"
                ),
            }
        ],
        temperature=0,
        # 有些兼容网关支持，有些不支持；支持就留着
        response_format={"type": "json_object"},
    )

    raw_text = resp.choices[0].message.content
    print("原始输出：")
    print(raw_text)

    cleaned = extract_json_text(raw_text)
    data = json.loads(cleaned)

    print("\n解析后：")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def test_reasoning():
    resp = client.chat.completions.create(
        model=model,
        reasoning_effort="low",
        messages=[
            {"role": "user", "content": "简单比较归并排序和快速排序。"}
        ],
        temperature=0.2,
    )
    print(resp.choices[0].message.content)


run_test("基础调用", test_basic)
run_test("流式输出", test_stream)
run_test("JSON 输出", test_json)
run_test("推理参数", test_reasoning)