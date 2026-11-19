import os
import json
from datetime import datetime
from openai import AzureOpenAI as OpenAI
from database import get_db_connection


# Azure OpenAI client (lazy init)
def get_azure_client():
    return OpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-12-01-preview",
    )


def generate_recommendations(user_profile: dict, lab_prices: list) -> dict:
    """
    AGENTIC AI RECOMMENDATION ENGINE using Azure OpenAI
    """
    today = datetime.now().strftime("%Y-%m-%d (%A)")

    # Prepare compact lab price summary (top 80 cheapest tests to keep prompt under limit)
    price_summary = []
    seen = set()
    for p in sorted(lab_prices, key=lambda x: x["price_inr"])[:80]:
        test_key = p["test_name"].upper()
        if test_key in seen:
            continue
        seen.add(test_key)
        price_summary.append(
            f"{p['test_name']} → ₹{p['price_inr']} (best at {p['lab_name']})"
        )

    # Medical history (truncated safely)
    history = user_profile.get("medical_history", "")[:6000]

    system_prompt = """
You are an Agentic Health AI Assistant for a smart preventive healthcare platform.
You act proactively, not reactively.
You analyze user profile, medical history, current date, personal events, and festival context (Jaipur, India).
Your goal is to give intelligent, cost-effective, personalized health test recommendations with clear "why" and "when".
"""

    user_prompt = f"""
Current date: {today}
User Profile:
- Name: {user_profile.get('name', 'User')}
- Age: {user_profile.get('age', 'unknown')} (DOB: {user_profile.get('dob')})
- Marital Status: {user_profile.get('marital_status', 'unknown')}
- Location: Jaipur
- Medical History Excerpt: {history or 'No history provided'}

Available Tests in Jaipur (with cheapest price across labs):
{chr(10).join(price_summary[:60])}

Festival / Cultural Context (Jaipur):
- April: Holi / New Year health detox
- October-November: Diwali / Post-festival detox & immunity

Digital Wellbeing (future data): [Not provided in this POC]

Task:
Act as an agentic AI. Reason step-by-step.
Generate 3-5 proactive recommendations (preventive checkups, relevant tests, packages).
Include:
- Best price & lab
- Clear clinical/lifestyle reason
- Trigger (birthday, festival, history, age, etc.)
- Urgency (this week / this month / next 3 months)

Return ONLY valid JSON in this exact schema:
{{
  "proactive_message": "short engaging message",
  "recommendations": [
    {{
      "package": "Test or Package Name",
      "best_price_inr": 1234,
      "best_lab": "Lab Name",
      "reason": "detailed why this is relevant for this user",
      "triggers": ["birthday", "diabetes history", "Diwali detox", ...],
      "urgency": "this month"
    }}
  ]
}}
"""

    try:
        client = get_azure_client()
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )

        content = response.choices[0].message.content.strip()
        result = json.loads(content)

        # Add user_id for frontend
        result["user_id"] = user_profile.get("user_id")
        return result

    except Exception as e:
        print(f"[Agentic AI] Azure OpenAI error: {e}")
        # Graceful fallback
        return {
            "user_id": user_profile.get("user_id"),
            "proactive_message": "🧠 Agentic AI is analyzing your profile...",
            "recommendations": [
                {
                    "package": "Complete Blood Count (CBC) + Lipid Profile",
                    "best_price_inr": 899,
                    "best_lab": "Dr B Lal Clinical Laboratory",
                    "reason": "Basic wellness screening - safe default while we process your full history",
                    "triggers": ["general preventive care"],
                    "urgency": "this month",
                }
            ],
        }
