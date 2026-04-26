import os
from openai import OpenAI
from dotenv import load_dotenv

# 1. Load environment variables from .env file
load_dotenv()

# 2. Initialize the OpenAI client
# It will retrieve the keys from your .env file automatically via os.getenv
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID")
)

def get_chat_response(prompt):
    try:
        # 3. Create a chat completion request
        response = client.chat.completions.create(
            model="gpt-4o",  # You can also use "gpt-4-turbo" or "gpt-3.5-turbo"
            messages=[
                {"role": "system", "content": "You are a helpful and witty assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        # 4. Extract and return the text content
        return response.choices[0].message.content

    except Exception as e:
        return f"An error occurred: {e}"

if __name__ == "__main__":
    user_query = "Explain the concept of 'Schrödinger's cat' in one sentence."
    print(f"User: {user_query}")
    
    answer = get_chat_response(user_query)
    print(f"AI: {answer}")