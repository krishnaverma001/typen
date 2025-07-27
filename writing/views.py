# writing/views.py

import os
import io
import zipfile
from django.conf import settings

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .models import UserImage, UsageStats
from .model.generator import HANDWRITING_GENERATOR

@login_required
@csrf_exempt
def generate(request):
    UsageStats.increment_generators()

    try:
        text = request.POST.get("text")
        style = int(request.POST.get("style", 0))
        bias = float(request.POST.get("bias"))
        stroke_width = float(request.POST.get("stroke_width"))
        use_margins = request.POST.get("use_margins", "false").lower() == "true"    # Hardcoded margin configuration

        if not text:
            return JsonResponse({"error": "No text provided."}, status=400)

        user = request.user
        output_dir = settings.IMG_DIR / user.username
        os.makedirs(output_dir, exist_ok=True)

        result = HANDWRITING_GENERATOR.generate_handwritten_pages(
            text=text,
            output_dir=output_dir,
            font_size_factor=0.9,
            handwriting_style=style,
            variation_level=bias,        # Low value: more uniform; High value: more randomness
            stroke_color='black',
            stroke_width=stroke_width,
            use_margins=use_margins      # Hardcoded: True = margins with border, False = minimal padding
        )

        filepaths = []
        for i in range(result["pages_generated"]):
            filename = f"page_{i + 1:03d}.svg"
            image_path = output_dir / filename

            # Read file from disk
            with open(image_path, 'rb') as f:
                data = f.read()

            # This is the actual path Django will save to
            relative_path = f"media/user/{request.user.username}/{filename}"

            # Remove the file *before* creating the object
            if default_storage.exists(relative_path):
                print("Deleting:", relative_path)
                default_storage.delete(relative_path)

            # Create the DB object
            image = UserImage(user=request.user)

            # Save the file using ContentFile (forces exact filename)
            image.image.save(filename, ContentFile(data), save=True)

            print("Saved as:", image.image.path)
            filepaths.append(image.image.url)

        return JsonResponse({
            "status": "success",
            "pages_generated": result["pages_generated"],
            "generation_time": result["generation_time"],
            "layout_mode": result["layout_mode"],  # New: shows "margins" or "padding"
            "files": filepaths
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)

@login_required
def home(request):
    UsageStats.increment_visitors()
    # stats = UsageStats.get()

    return render(request, 'writing/index.html', {
        # "visitors": stats.total_visitors,
        # "generators": stats.total_generators,

        "style_range": range(13),
    })