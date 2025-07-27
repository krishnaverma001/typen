import os
import logging
import numpy as np
import textwrap
import svgwrite
from pathlib import Path
import math
import time
import re

import drawing
from rnn import rnn


def sanitize_text(text, valid_chars):
    """Clean and sanitize input text for handwriting generation"""
    # Handle common unicode characters
    replacements = {
        '—': '-', '–': '-', '"': '"', '"': '"', ''': "'", ''': "'",
        '…': '...', '\u00a0': ' ', '\t': ' ', '\r': '',
        # Add more replacements as needed
        '°': 'deg', '±': '+/-', '×': 'x', '÷': '/',
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    # Remove invalid characters and normalize whitespace
    sanitized = ''.join(c for c in text if c in valid_chars)
    # Replace multiple whitespace with single space
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()

    return sanitized


class HandwritingGenerator(object):
    """Enhanced handwriting generator with A4 page support and auto-pagination"""

    # A4 dimensions at 96 DPI (web standard)
    A4_WIDTH_MM = 210
    A4_HEIGHT_MM = 297
    DPI = 96

    # Convert mm to pixels
    A4_WIDTH_PX = int(A4_WIDTH_MM * DPI / 25.4)  # ~794px
    A4_HEIGHT_PX = int(A4_HEIGHT_MM * DPI / 25.4)  # ~1123px

    # Page margins (in pixels)
    MARGIN_TOP = 120
    MARGIN_BOTTOM = 120
    MARGIN_LEFT = 100
    MARGIN_RIGHT = 100

    # Usable area
    USABLE_WIDTH = A4_WIDTH_PX - MARGIN_LEFT - MARGIN_RIGHT
    USABLE_HEIGHT = A4_HEIGHT_PX - MARGIN_TOP - MARGIN_BOTTOM

    # Line settings
    LINE_HEIGHT = 45  # Slightly increased for better readability
    MAX_LINES_PER_PAGE = USABLE_HEIGHT // LINE_HEIGHT  # Reserve space for page number

    def __init__(self):
        """Initialize the handwriting generator with pre-trained RNN model"""
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

        self.nn = rnn(
            log_dir='logs',
            checkpoint_dir='checkpoints',
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

    def estimate_chars_per_line(self, font_size_factor=1.0):
        """
        Estimate optimal characters per line based on usable width and average character spacing

        Args:
            font_size_factor (float): Scaling factor for character size estimation

        Returns:
            int: Estimated characters per line
        """
        # Conservative estimate: average character width including spacing
        avg_char_width = 14 * font_size_factor  # Adjusted for handwriting
        chars_per_line = int(self.USABLE_WIDTH / avg_char_width)

        # Ensure reasonable bounds
        return max(30, min(chars_per_line, 85))  # Between 30-85 chars per line

    def generate_handwritten_pages(self, text, output_dir="img/temp",
                                   font_size_factor=1.0, handwriting_style=None,
                                   variation_level=0.5, stroke_color='black',
                                   stroke_width=2, show_margins=True):
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
            show_margins (bool): Show page margins for debugging

        Returns:
            dict: Generation statistics
        """
        start_time = time.time()

        # Validate inputs
        if not text or not text.strip():
            raise ValueError("Input text cannot be empty")

        if not (0.3 <= font_size_factor <= 3.0):
            print(f"Warning: font_size_factor {font_size_factor} may produce poor results")

        # Clean and prepare text
        valid_chars = set(drawing.alphabet)
        clean_text = sanitize_text(text, valid_chars)

        if not clean_text:
            raise ValueError("No valid characters found in input text")

        print(f"Original text: {len(text)} characters")
        print(f"Clean text: {len(clean_text)} characters")

        # Calculate pagination parameters
        chars_per_line = self.estimate_chars_per_line(font_size_factor)
        print(f"Characters per line: {chars_per_line}")
        print(f"Max lines per page: {self.MAX_LINES_PER_PAGE}")

        # Smart text wrapping: preserve paragraphs and sentences
        lines = self._smart_text_wrap(clean_text, chars_per_line)
        total_pages = math.ceil(len(lines) / self.MAX_LINES_PER_PAGE)

        print(f"Text will span {len(lines)} lines across {total_pages} pages")

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate pages
        generated_files = []

        for page_num in range(total_pages):
            start_idx = page_num * self.MAX_LINES_PER_PAGE
            end_idx = min(start_idx + self.MAX_LINES_PER_PAGE, len(lines))
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
                show_margins=show_margins,
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
            'text_length': len(clean_text)
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

        # Split into paragraphs first
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

        all_lines = []

        for paragraph in paragraphs:
            # Wrap each paragraph
            wrapped_lines = textwrap.wrap(
                paragraph,
                width=chars_per_line,
                break_long_words=False,  # Don't break words
                break_on_hyphens=True,  # Allow breaks on hyphens
                expand_tabs=True,
                replace_whitespace=True
            )

            all_lines.extend(wrapped_lines)

            # Add small gap between paragraphs (empty line)
            if len(paragraphs) > 1 and paragraph != paragraphs[-1]:
                all_lines.append("")  # Empty line for paragraph break

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
                        biases=None, styles=None, stroke_colors=None,
                        stroke_widths=None, show_margins=True):
        """
        Render a single A4 page with handwritten text

        Args:
            filename (str): Output SVG filename
            lines (list): Text lines for this page
            page_number (int): Current page number
            total_pages (int): Total number of pages
            biases (list): Handwriting bias for each line
            styles (list): Handwriting style for each line
            stroke_colors (list): Stroke color for each line
            stroke_widths (list): Stroke width for each line
            show_margins (bool): Whether to show page margins
        """
        # Validate input lines
        valid_char_set = set(drawing.alphabet)
        for line_num, line in enumerate(lines):
            for char in line:
                if char not in valid_char_set:
                    print(f"Warning: Invalid character '{char}' in line {line_num}, skipping")
                    lines[line_num] = ''.join(c for c in line if c in valid_char_set)

        # Generate handwriting strokes
        strokes = self._generate_strokes(lines, biases, styles)
        is_sample = True

        # Create A4 SVG page
        self._draw_a4_page(
            strokes, lines, filename, stroke_colors, stroke_widths,
            page_number, total_pages, show_margins, is_sample
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
                    x_p = np.load(f'styles/style-{style}-strokes.npy')
                    c_p = np.load(f'styles/style-{style}-chars.npy').tostring().decode('utf-8')

                    # Combine style context with current line
                    combined_text = str(c_p) + " " + line
                    encoded = drawing.encode_ascii(combined_text)
                    encoded = np.array(encoded)

                    x_prime[i, :len(x_p), :] = x_p
                    x_prime_len[i] = len(x_p)
                    chars[i, :len(encoded)] = encoded
                    chars_len[i] = len(encoded)

                except (FileNotFoundError, IndexError, ValueError) as e:
                    print(f"Warning: Could not load style {styles[i] if styles else 'N/A'}, using default")
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
                      show_margins=True, is_sample=True):
        """Draw handwriting on A4 page with proper formatting"""
        stroke_colors = stroke_colors or ['black'] * len(lines)
        stroke_widths = stroke_widths or [2] * len(lines)

        # Create SVG with A4 dimensions
        dwg = svgwrite.Drawing(
            filename=filename,
            size=(f'{self.A4_WIDTH_PX}px', f'{self.A4_HEIGHT_PX}px')
        )
        dwg.viewbox(width=self.A4_WIDTH_PX, height=self.A4_HEIGHT_PX)

        # Add white background
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

        # Add subtle border around usable area (only if show_margins is True)
        if show_margins:
            border_offset = 40  # Small gap between border and text
            dwg.add(dwg.rect(
                insert=(self.MARGIN_LEFT - border_offset, self.MARGIN_TOP - border_offset),
                size=(self.USABLE_WIDTH + 2 * border_offset, self.USABLE_HEIGHT + 2 * border_offset),
                fill='none',
                stroke='#e0e0e0',
                stroke_width=1
            ))

        # Add page number footer (just the number)
        dwg.add(dwg.text(
            str(page_number),
            insert=(self.A4_WIDTH_PX // 2, self.A4_HEIGHT_PX - 40),
            text_anchor='middle',
            font_family='Arial, sans-serif',
            font_size='12px',
            fill='#666666'
        ))

        # Starting position for text (with border offset)
        current_y = self.MARGIN_TOP + 15

        # Render each line
        for i, (stroke_data, line, color, width) in enumerate(
                zip(strokes, lines, stroke_colors, stroke_widths)
        ):
            # Check if we have space for this line (leave room for page number)
            if current_y > (self.A4_HEIGHT_PX - self.MARGIN_BOTTOM):
                break  # Stop if we're too close to bottom

            if not line.strip():  # Empty line
                current_y += self.LINE_HEIGHT
                continue

            # Process stroke data
            if stroke_data is not None and len(stroke_data) > 0:
                # Scale and normalize strokes
                stroke_coords = stroke_data.copy()
                stroke_coords[:, :2] *= 1.4  # Adjust scaling for readability

                # Convert offsets to absolute coordinates
                stroke_coords = drawing.offsets_to_coords(stroke_coords)
                stroke_coords = drawing.denoise(stroke_coords)
                stroke_coords[:, :2] = drawing.align(stroke_coords[:, :2])

                # Flip Y axis and position on page
                stroke_coords[:, 1] *= -1
                min_x, min_y = stroke_coords[:, :2].min(axis=0)
                stroke_coords[:, :2] -= [min_x, min_y]

                # Position text within margins
                stroke_coords[:, 0] += self.MARGIN_LEFT
                stroke_coords[:, 1] += current_y

                # Scale if text is too wide
                max_x = stroke_coords[:, 0].max()
                if max_x > (self.A4_WIDTH_PX - self.MARGIN_RIGHT):
                    scale_factor = self.USABLE_WIDTH / (max_x - self.MARGIN_LEFT)
                    stroke_coords[:, 0] = self.MARGIN_LEFT + (stroke_coords[:, 0] - self.MARGIN_LEFT) * scale_factor

                # Create SVG path
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

    Args:
        text (str): Input text
        output_dir (str): Output directory
        **kwargs: Additional parameters for HandwritingGenerator

    Returns:
        dict: Generation statistics
    """
    generator = HandwritingGenerator()
    return generator.generate_handwritten_pages(text, output_dir, **kwargs)


# Example usage and testing
def main():
    """Demo script showing various usage examples"""

    # Example 1: Long text (multiple pages)
    long_text = """
    In the quiet town of Eldermoor, nestled between rolling hills and ancient forests, 
    a peculiar wind began to stir one late autumn evening. The villagers, wrapped in 
    coats and caution, noticed strange symbols appearing on the frost-covered windows — 
    not drawn by hand, but etched by something unseen. 
    
    Children whispered stories of a forgotten scribe who once penned spells so powerful 
    they could bend time itself. As the days grew shorter and the markings more complex, 
    an old historian named Elias uncovered an ancient journal in the library's cellar. 
    Its pages spoke of a quill made from a raven's feather, said to grant life to words 
    written with true intent.
    
    Drawn by curiosity and perhaps destiny, Elias set out to recreate the scribe's final 
    manuscript, unaware that each line he wrote would awaken something buried deep beneath 
    Eldermoor's cobbled streets. What began as a fascination with folklore soon spiraled 
    into a race against time as the village itself began to shift and groan.
    
    Old buildings leaned closer together, as if sharing secrets. Whispers echoed from 
    the empty woods beyond, carried by winds that seemed to have consciousness of their own. 
    The ink in Elias's pen refused to dry, remaining liquid and alive, pulsing with an 
    otherworldly energy that made the written words shimmer and dance upon the parchment.
    
    The city hummed with a rhythm all its own, a constant symphony of distant traffic, the murmur of conversations spilling from open windows, and the occasional chime of a street vendor. Sunlight, softened by a thin haze, painted the brick facades in warm hues of ochre and rose, highlighting the intricate details of cornices and lintels that often went unnoticed in the rush of daily life. Pigeons strutted confidently across worn pavements, their iridescent feathers catching the light, while an elderly woman carefully tended a small pot of marigolds on her windowsill, adding a splash of vibrant orange to the urban landscape. The air, thick with the scent of roasted coffee and the faint aroma of blooming jasmine, carried with it a sense of perpetual motion, a feeling that even in moments of stillness, the city was alive, breathing, and constantly evolving. Each passing face told a silent story, each faded advertisement hinted at a bygone era, and every shadow cast by a towering building whispered of the ceaseless passage of time, making the ordinary feel profoundly significant.
    """

    print("🖋️  Handwriting Generator Demo")
    print("=" * 50)

    try:
        # Initialize generator
        generator = HandwritingGenerator()

        # Generate long document with different styling
        print("\n📚 Generating long document...")
        handwriting = generator.generate_handwritten_pages(
            text=long_text,
            output_dir="img/v1",
            font_size_factor=0.9,
            handwriting_style=3,
            variation_level=0.6,
            stroke_color='black',
            stroke_width=1.5
        )

        print("\n✅ Demo completed successfully!")
        print(f"Long text: {handwriting['pages_generated']} pages in {handwriting['generation_time']}s")

    except Exception as e:
        print(f"❌ Error during generation: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()