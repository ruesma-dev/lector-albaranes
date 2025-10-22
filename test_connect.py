from openai import OpenAI

client = OpenAI(
  api_key="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"
)

response = client.responses.create(
  model="gpt-5-nano",
  input="write a haiku about ai",
  store=True,
)

print(response.output_text);
