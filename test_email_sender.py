from agents.email_sender import send_email

sample_headlines = [
    {
        "category": "tech",
        "headline": "Waymo reportedly raising a $16B funding round",
        "link": "https://techcrunch.com/"
    },
    {
        "category": "tech",
        "headline": "Meet the new European unicorns of 2026",
        "link": "https://techcrunch.com/"
    }
]

send_email(
    to_email="sudharsanreddy.saragada@gmail.com",
    headlines=sample_headlines
)

print("✅ Email sent successfully")
