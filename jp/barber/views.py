import json
from django.shortcuts import render
from django.templatetags.static import static

def home(request):
    cuts = [
        {
            "name": "Skin Fade",
            "time": "30-40 min",
            "price": "$40",
            "desc": "Clean fade from skin up with a sharp, blended finish. Our most popular cut.",
            "category": "Fade",
            "image_url": static("Cuts/fade1.webp"),
            "gallery": "|".join([
                static("Cuts/fade1.webp"),
                static("Cuts/fade2.webp"),
            ]),
        },
        {
            "name": "Buzz Cut",
            "time": "15-25 min",
            "price": "$25",
            "desc": "Simple, sharp, and low-maintenance. Even length all around with a crisp lineup.",
            "category": "Classic",
            "image_url": static("Cuts/buzz1.webp"),
            "gallery": "|".join([
                static("Cuts/buzz1.webp"),
            ]),
        },
        {
            "name": "Classic Taper",
            "time": "30-40 min",
            "price": "$35",
            "desc": "Timeless taper with a clean neckline. Works with any hair type and length.",
            "category": "Taper",
            "image_url": static("Cuts/fade2.webp"),
            "gallery": "|".join([
                static("Cuts/fade2.webp"),
                static("Cuts/fade1.webp"),
            ]),
        },
        {
            "name": "Fade + Beard",
            "time": "45-55 min",
            "price": "$55",
            "desc": "Full fade with detailed beard shaping, lineup, and hot towel finish.",
            "category": "Combo",
            "image_url": static("Cuts/fade3.jpg"),
            "gallery": "|".join([
                static("Cuts/fade3.jpg"),
                static("Cuts/fade1.webp"),
                static("Cuts/fade2.webp"),
            ]),
        },
    ]

    barbers = [
        {
            "id": "jp",
            "name": "JP",
            "title": "Owner / Lead Barber",
            "photo_url": "https://picsum.photos/800/1100?random=30",
            "bio": "Started cutting hair at 16 out of my parents' basement. "
                   "Fifteen years later, I'm still obsessed with getting every "
                   "fade, lineup, and taper right. I built this shop to be the "
                   "kind of place I always wanted to walk into — no ego, no rush, "
                   "just sharp work and good conversation.",
            "reviews": [
                {
                    "author": "Marcus T.",
                    "text": "Best fade I've ever had. JP actually listens to what "
                            "you want and delivers every single time.",
                },
                {
                    "author": "David L.",
                    "text": "Been coming here for two years now. Never once left "
                            "disappointed. The man is consistent.",
                },
                {
                    "author": "Ryan K.",
                    "text": "JP fixed a haircut another barber messed up. Didn't "
                            "even charge extra. That's the kind of guy he is.",
                },
            ],
        },
        {
            "id": "mike",
            "name": "Mike",
            "title": "Senior Barber",
            "photo_url": "https://picsum.photos/800/1100?random=31",
            "bio": "Trained classically, but I stay current. I like working with "
                   "texture — whether that's a crop, a blowout, or a beard shape. "
                   "My thing is making sure you leave looking like yourself, just "
                   "a sharper version. If you're not sure what you want, I'll "
                   "figure it out with you.",
            "reviews": [
                {
                    "author": "James W.",
                    "text": "Mike has a gift for figuring out what works with your "
                            "face shape. I just sit down and trust him.",
                },
                {
                    "author": "Chris P.",
                    "text": "Always a chill experience. Good music, good "
                            "conversation, and a clean cut every time.",
                },
            ],
        },
    ]

    # Pre-serialize barber data to JSON for safe template embedding
    for barber in barbers:
        barber["data_json"] = json.dumps({
            "photo": barber["photo_url"],
            "name": barber["name"],
            "title": barber["title"],
            "bio": barber["bio"],
            "reviews": barber["reviews"],
        })

    # Background image — replace with your own image in static/bg/
    # Set to empty string to disable background image
    background_image = ""  # e.g., static("bg/background.webp")

    return render(request, "home.html", {
        "cuts": cuts,
        "barbers": barbers,
        "background_image": background_image,
    })
