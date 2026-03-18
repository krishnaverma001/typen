# writing/views.py

import os
import io
import zipfile
import logging
from django.conf import settings

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .models import UserImage, UsageStats, Generation
from .ml.generator import HANDWRITING_GENERATOR

# Configure logger for this module
logger = logging.getLogger(__name__)

@login_required
@csrf_exempt
def generate(request):
    logger.info(f"User: {request.user}")
    UsageStats.increment_generators()

    try:
        text = request.POST.get("text")
        style = int(request.POST.get("style", 0))
        bias = float(request.POST.get("bias"))
        stroke_width = float(request.POST.get("stroke_width"))
        use_margins = request.POST.get("use_margins", "false").lower() == "true"
        
        logger.info(f"Parameters - Style: {style}, Bias: {bias}, Stroke: {stroke_width}, Margins: {use_margins}")
        logger.info(f"Text length: {len(text) if text else 0}")

        if not text:
            logger.warning("No text provided in request")
            return JsonResponse({"error": "No text provided."}, status=400)

        user = request.user
        
        # Create Generation record first to get session_id
        logger.info("Creating Generation record...")
        generation = Generation.objects.create(
            user=user,
            text_input=text,
            parameters={
                "style": style,
                "bias": bias,
                "stroke_width": stroke_width,
                "use_margins": use_margins,
            },
            pages_generated=0,  # Will update after generation
            generation_time=0.0,
        )
        logger.info(f"Generation created - ID: {generation.session_id}")

        # Create session-specific directory for output
        session_output_dir = settings.IMG_DIR / user.username / f"gen_{generation.session_id}"
        os.makedirs(session_output_dir, exist_ok=True)
        logger.info(f"Session output directory: {session_output_dir}")

        logger.info("Starting handwriting generation...")
        result = HANDWRITING_GENERATOR.generate_handwritten_pages(
            text=text,
            output_dir=session_output_dir,
            font_size_factor=0.9,
            handwriting_style=style,
            variation_level=bias,        # Low value: more uniform; High value: more randomness
            stroke_color='black',
            stroke_width=stroke_width,
            use_margins=use_margins      # Hardcoded: True = margins with border, False = minimal padding
        )

        # Update generation with results
        generation.pages_generated = result["pages_generated"]
        generation.generation_time = result["generation_time"]
        generation.save()
        logger.info(f"Generation updated with {result['pages_generated']} pages")

        filepaths = []
        for i in range(result["pages_generated"]):
            logger.info(f"Processing page {i + 1}/{result['pages_generated']}")
            filename = f"page_{i + 1:03d}.svg"
            image_path = session_output_dir / filename
            logger.info(f"Page file path: {image_path}")

            # Read file from disk (already in session directory)
            with open(image_path, 'rb') as f:
                data = f.read()
            logger.info(f"Read {len(data)} bytes from {filename}")

            # Create the DB object with Generation link
            image = UserImage(user=user, generation=generation)
            logger.info(f"UserImage instance created for generation {generation.session_id}")

            # Save the file using ContentFile (forces exact filename)
            # The upload_to function will place it in gen_{session_id}/ directory
            image.image.save(filename, ContentFile(data), save=True)
            logger.info(f"Saved to: {image.image.path}")
            logger.info(f"File URL: {image.image.url}")
            
            filepaths.append(image.image.url)

        return JsonResponse({
            "status": "success",
            "generation_id": str(generation.session_id),
            "pages_generated": result["pages_generated"],
            "generation_time": result["generation_time"],
            "layout_mode": result["layout_mode"],  # New: shows "margins" or "padding"
            "files": filepaths
        })

    except Exception as e:
        logger.error(f"GENERATE ERROR: {str(e)}", exc_info=True)
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


@login_required
def generation_history(request):
    """Get paginated list of user's generations (newest first)."""
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    
    try:
        page = int(page)
        per_page = int(per_page)
    except (ValueError, TypeError):
        page = 1
        per_page = 10
    
    logger.info(f"Page: {page}, Per page: {per_page}")
    
    # Get all generations for the user
    generations = Generation.objects.filter(user=request.user).prefetch_related('pages')
    total_count = generations.count()
    logger.info(f"Total generations found: {total_count}")
    
    # Calculate pagination
    start = (page - 1) * per_page
    end = start + per_page
    paginated_gens = generations[start:end]
    logger.info(f"Paginated results: {len(list(paginated_gens))} items")
    
    # Build response data
    generations_data = []
    for gen in paginated_gens:
        logger.info(f"Generation {gen.session_id}: {gen.pages_generated} pages")
        generations_data.append({
            "generation_id": str(gen.session_id),
            "created_at": gen.created_at.isoformat(),
            "text_preview": gen.text_input[:100] + ("..." if len(gen.text_input) > 100 else ""),
            "pages_generated": gen.pages_generated,
            "generation_time": gen.generation_time,
            "parameters": gen.parameters,
        })
    
    return JsonResponse({
        "status": "success",
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": (total_count + per_page - 1) // per_page,
        "generations": generations_data,
    })


@login_required
def generation_detail(request, generation_id):
    """Retrieve specific generation's pages and metadata."""
    try:
        generation = Generation.objects.get(session_id=generation_id, user=request.user)
        logger.info(f"Generation found: {generation.session_id}")
    except Generation.DoesNotExist:
        logger.error(f"Generation not found: {generation_id}")
        return JsonResponse({"error": "Generation not found"}, status=404)
    
    pages = generation.pages.order_by('id')
    logger.info(f"Found {len(list(pages))} pages for generation")
    pages_data = [
        {
            "page_id": page.id,
            "file_url": page.image.url,
            "created_at": page.created_at.isoformat(),
        }
        for page in pages
    ]

    return JsonResponse({
        "status": "success",
        "generation_id": str(generation.session_id),
        "created_at": generation.created_at.isoformat(),
        "text_input": generation.text_input,
        "parameters": generation.parameters,
        "pages_generated": generation.pages_generated,
        "generation_time": generation.generation_time,
        "pages": pages_data,
    })