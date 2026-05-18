import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv(".env.local")
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model=os.environ.get('DEEPSEEK_MODEL'),
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "你是什么模型？"},
    ],
    stream=False,
    reasoning_effort="max",
    extra_body={"thinking": {"type": "enabled"}}
)

print(response.choices[0].message.content)