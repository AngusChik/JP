from django.shortcuts import render
from django.templatetags.static import static

def home(request):
    cuts = [
        {
            "name": "Skin Fade",
            "time": "30–40 min",
            "desc": "Clean fade with sharp finish",
            "category": "Service",
            "image_url": static("Cuts/fade1.webp"),
            "gallery": "|".join([
                static("Cuts/fade1.webp"),
                static("Cuts/fade2.webp"),
            ]),
        },
        {
            "name": "Buzz Cut",
            "time": "15–25 min",
            "desc": "Simple and sharp.",
            "category": "Service",
            "image_url": static("Cuts/buzz1.webp"),
            "gallery": "|".join([
                static("Cuts/buzz1.webp"),
                static("Cuts/fade1.webp"),   # swap/replace with real buzz pics later
            ]),
        },
        {
            "name": "Classic Taper",
            "time": "30–40 min",
            "desc": "Timeless taper + neckline.",
            "category": "Service",
            "image_url": static("Cuts/fade2.webp"),
            "gallery": "|".join([
                static("Cuts/fade2.webp"),
                static("Cuts/fade1.webp"),
            ]),
        },
                {
            "name": "Classic Taper",
            "time": "30–40 min",
            "desc": "Timeless taper + neckline.",
            "category": "Service",
            "image_url": static("Cuts/fade2.webp"),
            "gallery": "|".join([
                static("Cuts/fade2.webp"),
                static("Cuts/fade1.webp"),
            ]),
        },
                {
            "name": "Classic Taper",
            "time": "30–40 min",
            "desc": "Timeless taper + neckline.",
            "category": "Service",
            "image_url": static("Cuts/fade2.webp"),
            "gallery": "|".join([
                static("Cuts/fade2.webp"),
                static("Cuts/fade1.webp"),
            ]),
        },
    ]

    return render(request, "home.html", {"cuts": cuts})
