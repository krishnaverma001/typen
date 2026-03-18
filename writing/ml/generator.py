# generator.py

import os
import logging
from functools import lru_cache

import numpy as np
import textwrap
import svgwrite
from pathlib import Path
import math
import time
import re

from config import settings
from . import drawing
from .rnn import rnn

CHECKPOINTS_DIR = settings.CHECKPOINTS_DIR
STYLES_DIR = settings.STYLES_DIR
LOGS_DIR = settings.LOGS_DIR

@lru_cache(maxsize=32)
def load_style_files(style_id):
    strokes = np.load(STYLES_DIR / f'style-{style_id}-strokes.npy')
    chars = np.load(STYLES_DIR / f'style-{style_id}-chars.npy').tobytes().decode('utf-8')
    return strokes, chars

def sanitize_text(text, valid_chars):
    """Clean and sanitize input text for handwriting generation"""
    replacements = {
        '—': '-', '–': '-', '"': '"', '"': '"', ''': "'", ''': "'",
        '…': '...', '\u00a0': ' ', '\t': ' ', '\r': '',
        '°': 'deg', '±': '+/-', '×': 'x', '÷': '/',
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    lines = text.split('\n')
    sanitized_lines = []

    for line in lines:
        # Keep only valid characters
        clean_line = ''.join(c for c in line if c in valid_chars)

        # Normalize spaces
        clean_line = re.sub(r'\s+', ' ', clean_line).strip()
        sanitized_lines.append(clean_line)

    # Reconstruct text with original line breaks
    return '\n'.join(sanitized_lines)

class HandwritingGenerator(object):
    """Enhanced handwriting generator with A4 page support and auto-pagination"""

    # A4 dimensions at 96 DPI (web standard)
    A4_WIDTH_MM = 210
    A4_HEIGHT_MM = 297
    DPI = 96

    # Convert mm to pixels
    A4_WIDTH_PX = int(A4_WIDTH_MM * DPI / 25.4)  # ~794px
    A4_HEIGHT_PX = int(A4_HEIGHT_MM * DPI / 25.4)  # ~1123px

    # Default margin settings
    DEFAULT_MARGIN_TOP = 120
    DEFAULT_MARGIN_BOTTOM = 120
    DEFAULT_MARGIN_LEFT = 100
    DEFAULT_MARGIN_RIGHT = 100

    # Default padding settings (when margins are disabled)
    DEFAULT_PADDING_TOP = 60
    DEFAULT_PADDING_BOTTOM = 60
    DEFAULT_PADDING_LEFT = 40
    DEFAULT_PADDING_RIGHT = 40

    # Line settings
    LINE_HEIGHT = 45  # Slightly increased for better readability

    def __init__(self):
        """Initialize the handwriting generator with pre-trained RNN model"""
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

        self.nn = rnn(
            log_dir=LOGS_DIR,
            checkpoint_dir=CHECKPOINTS_DIR,
            prediction_dir='predictions',
            learning_rates=[.0001, .00005, .00002],
            batch_sizes=[32, 64, 64],
            patiences=[1500, 1000, 500],
            beta1_decays=[.9, .9, .9],
            validation_batch_size=32,
            optimizer='rms',
            num_training_steps=100000,
            warm_start_init_step=17900,
            regularization_constant=0.0,
            keep_prob=1.0,
            enable_parameter_averaging=False,
            min_steps_to_checkpoint=2000,
            log_interval=20,
            logging_level=logging.CRITICAL,
            grad_clip=10,
            lstm_size=400,
            output_mixture_components=20,
            attention_mixture_components=10
        )

        print("Loading pre-trained handwriting model...")
        self.nn.restore()
        print("Model loaded successfully!")

    def _calculate_page_layout(self, use_margins=True, margin_top=None, margin_bottom=None,
                             margin_left=None, margin_right=None):
        """
        Calculate page layout parameters based on margin settings

        Args:
            use_margins (bool): Whether to use proper margins or just padding
            margin_top, margin_bottom, margin_left, margin_right (int): Custom margin values

        Returns:
            dict: Layout parameters
        """
        if use_margins:
            # Use provided margins or defaults
            top = margin_top if margin_top is not None else self.DEFAULT_MARGIN_TOP
            bottom = margin_bottom if margin_bottom is not None else self.DEFAULT_MARGIN_BOTTOM
            left = margin_left if margin_left is not None else self.DEFAULT_MARGIN_LEFT
            right = margin_right if margin_right is not None else self.DEFAULT_MARGIN_RIGHT
        else:
            # Use minimal padding
            top = margin_top if margin_top is not None else self.DEFAULT_PADDING_TOP
            bottom = margin_bottom if margin_bottom is not None else self.DEFAULT_PADDING_BOTTOM
            left = margin_left if margin_left is not None else self.DEFAULT_PADDING_LEFT
            right = margin_right if margin_right is not None else self.DEFAULT_PADDING_RIGHT

        usable_width = self.A4_WIDTH_PX - left - right
        usable_height = self.A4_HEIGHT_PX - top - bottom
        max_lines_per_page = usable_height // self.LINE_HEIGHT

        return {
            'margin_top': top,
            'margin_bottom': bottom,
            'margin_left': left,
            'margin_right': right,
            'usable_width': usable_width,
            'usable_height': usable_height,
            'max_lines_per_page': max_lines_per_page,
            'use_margins': use_margins
        }

    def estimate_chars_per_line(self, font_size_factor=1.0, layout_params=None):
        """
        Estimate optimal characters per line based on usable width and average character spacing

        Args:
            font_size_factor (float): Scaling factor for character size estimation
            layout_params (dict): Layout parameters from _calculate_page_layout

        Returns:
            int: Estimated characters per line
        """
        if layout_params is None:
            layout_params = self._calculate_page_layout()

        # Conservative estimate: average character width including spacing
        avg_char_width = 14 * font_size_factor  # Adjusted for handwriting
        chars_per_line = int(layout_params['usable_width'] / avg_char_width)

        # Ensure reasonable bounds
        return max(30, min(chars_per_line, 85))  # Between 30-85 chars per line

    def generate_handwritten_pages(self, text, output_dir="img/temp",
                                   font_size_factor=1.0, handwriting_style=None,
                                   variation_level=0.5, stroke_color='black',
                                   stroke_width=2, use_margins=True,
                                   margin_top=None, margin_bottom=None,
                                   margin_left=None, margin_right=None):
        """
        Main method: Convert any text into handwritten A4 pages with automatic pagination

        Args:
            text (str): Input text of any length
            output_dir (str): Directory to save generated SVG pages
            font_size_factor (float): Size scaling (0.5-2.0 recommended)
            handwriting_style (int): Style number (0-20, None for default)
            variation_level (float): Writing variation (0.0-1.0)
            stroke_color (str): Pen color
            stroke_width (int): Pen thickness
            use_margins (bool): Whether to use proper margins (True) or minimal padding (False)
            margin_top, margin_bottom, margin_left, margin_right (int): Custom margin/padding values

        Returns:
            dict: Generation statistics
        """
        start_time = time.time()

        # Validate inputs
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty")

        if not (0.3 <= font_size_factor <= 3.0):
            print(f"Warning: font_size_factor {font_size_factor} may produce poor results")

        # Calculate page layout
        layout_params = self._calculate_page_layout(
            use_margins=use_margins,
            margin_top=margin_top,
            margin_bottom=margin_bottom,
            margin_left=margin_left,
            margin_right=margin_right
        )

        # Clean and prepare text
        valid_chars = set(drawing.alphabet)
        clean_text = sanitize_text(text, valid_chars)

        if not clean_text:
            raise ValueError("No valid characters found in input text")

        print(f"Original text: {len(text)} characters")
        print(f"Clean text: {len(clean_text)} characters")
        print(f"Layout mode: {'Margins' if use_margins else 'Padding'}")

        # Calculate pagination parameters
        chars_per_line = self.estimate_chars_per_line(font_size_factor, layout_params)
        print(f"Characters per line: {chars_per_line}")
        print(f"Max lines per page: {layout_params['max_lines_per_page']}")

        # Smart text wrapping: preserve paragraphs and sentences
        lines = self._smart_text_wrap(clean_text, chars_per_line)
        total_pages = math.ceil(len(lines) / layout_params['max_lines_per_page'])

        print(f"Text will span {len(lines)} lines across {total_pages} pages")

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate pages
        generated_files = []

        for page_num in range(total_pages):
            start_idx = page_num * layout_params['max_lines_per_page']
            end_idx = min(start_idx + layout_params['max_lines_per_page'], len(lines))
            page_lines = lines[start_idx:end_idx]

            # Create varied parameters for natural handwriting
            page_params = self._generate_page_parameters(
                page_lines, handwriting_style, variation_level,
                stroke_color, stroke_width
            )

            filename = os.path.join(output_dir, f"page_{page_num + 1:03d}.svg")

            self._render_a4_page(
                filename=filename,
                lines=page_lines,
                page_number=page_num + 1,
                total_pages=total_pages,
                layout_params=layout_params,
                **page_params
            )

            generated_files.append(filename)
            print(f"✓ Generated page {page_num + 1}/{total_pages}: {len(page_lines)} lines")

        generation_time = time.time() - start_time

        # Return statistics
        stats = {
            'pages_generated': total_pages,
            'total_lines': len(lines),
            'chars_per_line': chars_per_line,
            'generation_time': round(generation_time, 2),
            'output_files': generated_files,
            'text_length': len(clean_text),
            'layout_mode': 'margins' if use_margins else 'padding'
        }

        print(f"\n🎉 Generation complete!")
        print(f"📄 Pages: {total_pages}")
        print(f"⏱️  Time: {stats['generation_time']}s")
        print(f"📁 Output: {output_dir}/")

        return stats

    def _smart_text_wrap(self, text, chars_per_line):
        """
        Intelligently wrap text preserving natural breaks

        Args:
            text (str): Clean input text
            chars_per_line (int): Target characters per line

        Returns:
            list: List of text lines
        """

        paragraphs = text.split('\n')  # Don't strip; keep blank lines
        all_lines = []

        for paragraph in paragraphs:
            if not paragraph.strip():
                all_lines.append("")  # Preserve blank lines
                continue

            wrapped_lines = textwrap.wrap(
                paragraph,
                width=chars_per_line,
                break_long_words=False,
                break_on_hyphens=True,
                expand_tabs=True,
                replace_whitespace=True
            )
            all_lines.extend(wrapped_lines)

        return all_lines

    def _generate_page_parameters(self, lines, style, variation, color, width):
        """Generate natural handwriting parameters for a page"""
        num_lines = len(lines)

        # Generate biases (writing randomness/slant)
        base_bias = 0.3 + variation * 0.4  # 0.3 to 0.7 range
        biases = [
            base_bias + np.random.normal(0, 0.1)
            for _ in range(num_lines)
        ]
        biases = [max(0.1, min(0.9, b)) for b in biases]  # Clamp to valid range

        # Generate styles
        if style is not None:
            # Use specified style with slight variations
            styles = [style] * num_lines
        else:
            # Use varied styles for natural look
            base_style = np.random.randint(0, 12)  # Assuming 12 available styles
            styles = [base_style] * num_lines

        # Generate colors and widths
        stroke_colors = [color] * num_lines
        stroke_widths = [width] * num_lines

        return {
            'biases': biases,
            'styles': styles,
            'stroke_colors': stroke_colors,
            'stroke_widths': stroke_widths
        }

    def _render_a4_page(self, filename, lines, page_number=1, total_pages=1,
                        layout_params=None, biases=None, styles=None,
                        stroke_colors=None, stroke_widths=None):
        """
        Render a single A4 page with handwritten text

        Args:
            filename (str): Output SVG filename
            lines (list): Text lines for this page
            page_number (int): Current page number
            total_pages (int): Total number of pages
            layout_params (dict): Layout parameters from _calculate_page_layout
            biases (list): Handwriting bias for each line
            styles (list): Handwriting style for each line
            stroke_colors (list): Stroke color for each line
            stroke_widths (list): Stroke width for each line
        """
        if layout_params is None:
            layout_params = self._calculate_page_layout()

        # Validate input lines
        valid_char_set = set(drawing.alphabet)
        for line_num, line in enumerate(lines):
            for char in line:
                if char not in valid_char_set:
                    print(f"Warning: Invalid character '{char}' in line {line_num}, skipping")
                    lines[line_num] = ''.join(c for c in line if c in valid_char_set)

        # Generate handwriting strokes
        strokes = self._generate_strokes(lines, biases, styles)
        is_sample = False

        # Create A4 SVG page
        self._draw_a4_page(
            strokes, lines, filename, stroke_colors, stroke_widths,
            page_number, total_pages, layout_params, is_sample
        )

    def _generate_strokes(self, lines, biases=None, styles=None):
        """Generate handwriting stroke data using the neural network"""
        if not lines:
            return []

        num_samples = len(lines)
        max_tsteps = 40 * max([len(line) for line in lines if line]) if any(lines) else 40
        biases = biases if biases is not None else [0.5] * num_samples

        # Prepare input arrays
        x_prime = np.zeros([num_samples, 1200, 3])
        x_prime_len = np.zeros([num_samples])
        chars = np.zeros([num_samples, 120])
        chars_len = np.zeros([num_samples])

        # Handle styles and character encoding
        for i, line in enumerate(lines):
            if styles is not None and i < len(styles):
                try:
                    # Load style-specific data
                    style = styles[i]

                    x_p, c_p = load_style_files(style)

                    # Combine style context with current line
                    combined_text = str(c_p) + " " + line
                    encoded = drawing.encode_ascii(combined_text)
                    encoded = np.array(encoded)

                    x_prime[i, :len(x_p), :] = x_p
                    x_prime_len[i] = len(x_p)
                    chars[i, :len(encoded)] = encoded
                    chars_len[i] = len(encoded)

                except (FileNotFoundError, IndexError, ValueError) as e:
                    # Fall back to default encoding
                    encoded = drawing.encode_ascii(line)
                    chars[i, :len(encoded)] = encoded
                    chars_len[i] = len(encoded)
            else:
                # Default encoding without style
                encoded = drawing.encode_ascii(line)
                chars[i, :len(encoded)] = encoded
                chars_len[i] = len(encoded)

        # Generate handwriting using neural network
        try:
            [samples] = self.nn.session.run(
                [self.nn.sampled_sequence],
                feed_dict={
                    self.nn.prime: styles is not None,
                    self.nn.x_prime: x_prime,
                    self.nn.x_prime_len: x_prime_len,
                    self.nn.num_samples: num_samples,
                    self.nn.sample_tsteps: max_tsteps,
                    self.nn.c: chars,
                    self.nn.c_len: chars_len,
                    self.nn.bias: biases
                }
            )

            # Clean up samples (remove zero padding)
            samples = [sample[~np.all(sample == 0.0, axis=1)] for sample in samples]
            return samples

        except Exception as e:
            print(f"Error generating strokes: {e}")
            return [np.array([[0, 0, 1]])] * len(lines)  # Fallback

    def _draw_a4_page(self, strokes, lines, filename, stroke_colors=None,
                  stroke_widths=None, page_number=1, total_pages=1,
                  layout_params=None, is_sample=True):

        """Draw handwriting on A4 page with proper formatting"""
        if layout_params is None:
            layout_params = self._calculate_page_layout()

        stroke_colors = stroke_colors or ['black'] * len(lines)
        stroke_widths = stroke_widths or [2] * len(lines)

        # Create SVG WITHOUT fixed pixel dimensions
        dwg = svgwrite.Drawing(filename=filename)

        # Set viewBox to define the coordinate system (keeps A4 proportions)
        dwg.viewbox(width=self.A4_WIDTH_PX, height=self.A4_HEIGHT_PX)

        # Make SVG responsive by NOT setting width/height attributes
        # Instead, add preserveAspectRatio for proper scaling
        dwg.attribs['preserveAspectRatio'] = 'xMidYMin meet'

        # Add CSS to ensure responsive behavior
        dwg.add(dwg.style("""
            svg {
                width: 100%;
                height: auto;
                max-width: 100%;
            }
        """))

        # Add white background (using viewBox coordinates)
        dwg.add(dwg.rect(
            insert=(0, 0),
            size=(self.A4_WIDTH_PX, self.A4_HEIGHT_PX),
            fill='white',
            stroke='none'
        ))

        # Watermark for page
        if is_sample:
            dwg.add(dwg.text(
                'SAMPLE',
                insert=(self.A4_WIDTH_PX / 2, self.A4_HEIGHT_PX / 2),
                text_anchor="middle",
                alignment_baseline="middle",
                font_size=90,
                fill='gray',
                fill_opacity=0.3,
                transform=f'rotate(-45, {self.A4_WIDTH_PX / 2}, {self.A4_HEIGHT_PX / 2})'
            ))

        # Add visual margin indicator only if using margins (not padding)
        if layout_params['use_margins']:
            border_offset = 20
            dwg.add(dwg.rect(
                insert=(layout_params['margin_left'] - border_offset,
                       layout_params['margin_top'] - border_offset),
                size=(layout_params['usable_width'] + 2 * border_offset,
                     layout_params['usable_height'] + 2 * border_offset),
                fill='none',
                stroke='#aaa',
                stroke_width=1,
            ))

        # Add page number footer
        dwg.add(dwg.text(
            str(page_number),
            insert=(self.A4_WIDTH_PX // 2, self.A4_HEIGHT_PX - 40),
            text_anchor='middle',
            font_family='Arial, sans-serif',
            font_size='12px',
            fill='#666666'
        ))

        # Starting position for text
        current_y = layout_params['margin_top'] + 15

        # Render each line
        for i, (stroke_data, line, color, width) in enumerate(
                zip(strokes, lines, stroke_colors, stroke_widths)
        ):
            if current_y > (self.A4_HEIGHT_PX - layout_params['margin_bottom']):
                break

            if not line.strip():
                current_y += self.LINE_HEIGHT
                continue

            if stroke_data is not None and len(stroke_data) > 0:
                stroke_coords = stroke_data.copy()
                stroke_coords[:, :2] *= 1.4

                stroke_coords = drawing.offsets_to_coords(stroke_coords)
                stroke_coords = drawing.denoise(stroke_coords)
                stroke_coords[:, :2] = drawing.align(stroke_coords[:, :2])

                stroke_coords[:, 1] *= -1
                min_x, min_y = stroke_coords[:, :2].min(axis=0)
                stroke_coords[:, :2] -= [min_x, min_y]

                stroke_coords[:, 0] += layout_params['margin_left']
                stroke_coords[:, 1] += current_y

                max_x = stroke_coords[:, 0].max()
                if max_x > (self.A4_WIDTH_PX - layout_params['margin_right']):
                    scale_factor = layout_params['usable_width'] / (max_x - layout_params['margin_left'])
                    stroke_coords[:, 0] = layout_params['margin_left'] + (stroke_coords[:, 0] - layout_params['margin_left']) * scale_factor

                path_data = self._create_svg_path(stroke_coords)

                if path_data:
                    path = svgwrite.path.Path(path_data)
                    path = path.stroke(
                        color=color,
                        width=width,
                        linecap='round',
                        linejoin='round'
                    ).fill('none')
                    dwg.add(path)

            current_y += self.LINE_HEIGHT

        # Save SVG
        dwg.save()

    def _create_svg_path(self, stroke_coords):
        """Convert stroke coordinates to SVG path data"""
        if len(stroke_coords) == 0:
            return ""

        path_data = ""
        pen_up = True

        for i, (x, y, end_of_stroke) in enumerate(stroke_coords):
            if pen_up:
                path_data += f"M{x:.2f},{y:.2f} "
                pen_up = False
            else:
                path_data += f"L{x:.2f},{y:.2f} "

            # Lift pen at end of stroke
            if end_of_stroke > 0.5:
                pen_up = True

        return path_data


# Convenience functions for backward compatibility and easy usage
def generate_handwritten_document(text, output_dir="img/temp", **kwargs):
    """
    Convenience function to generate handwritten document from text
    """
    return HANDWRITING_GENERATOR.generate_handwritten_pages(
        text, output_dir=output_dir, **kwargs
    )


HANDWRITING_GENERATOR = HandwritingGenerator()