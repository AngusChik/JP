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

    return render(request, "home.html", {"cuts": cuts})
