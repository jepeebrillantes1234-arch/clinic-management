"""Small dependency-free PDF exports for student and clinic reports."""

import textwrap
import math
import zlib

from PIL import Image

from django.http import HttpResponse
from django.utils import timezone


class PDFDocument:
    def __init__(self, landscape=False, title="Clinic Management System"):
        self.width, self.height = (842, 595) if landscape else (595, 842)
        self.pages = []
        self.commands = []
        self.y = self.height - 48
        self.title = title
        self.watermark = None
        self.header_lines = []

    def set_watermark(self, image_path, opacity=0.10, max_size=(360, 390)):
        """Prepare an embedded, centered PNG watermark for every page."""
        with Image.open(image_path) as source:
            image = source.convert("RGBA")
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            background.alpha_composite(image)
            rgb = background.convert("RGB")
            raw = zlib.compress(rgb.tobytes())
        width, height = rgb.size
        x, y = (self.width - width) / 2, (self.height - height) / 2
        self.watermark = {"width": width, "height": height, "data": raw, "opacity": max(0, min(1, opacity)), "x": x, "y": y}

    def set_header(self, lines):
        self.header_lines = list(lines)

    def _draw_page_header(self):
        if self.watermark:
            self.commands.append(
                f"q /Watermark gs {self.watermark['width']} 0 0 {self.watermark['height']} "
                f"{self.watermark['x']:.2f} {self.watermark['y']:.2f} cm /Logo Do Q"
            )
        if self.header_lines:
            y = self.height - 34
            for index, line in enumerate(self.header_lines):
                size = 11 if index == 0 else 8.5
                safe = self._safe(line)
                x = (self.width - len(safe) * size * 0.52) / 2
                color = (0.08, 0.25, 0.42) if index == 0 else (0.35, 0.41, 0.48)
                self.text(x, y, safe, size, bold=(index == 0), color=color)
                y -= 14
            self.rule(38, y + 2, self.width - 38, (0.78, 0.84, 0.90))
            self.y = y - 13

    def _new_page(self):
        first_page = not self.pages
        self.commands = []
        self.pages.append(self.commands)
        self.y = self.height - 46
        self._draw_page_header()
        if not first_page and not self.header_lines:
            self.text(38, self.y, self.title, 8, bold=True, color=(0.12, 0.27, 0.42))
            self.y -= 18

    def graphic_page(self, background=(1, 1, 1)):
        self.commands = []
        self.pages.append(self.commands)
        self.y = self.height - 42
        self.rectangle(0, 0, self.width, self.height, background)
        self._draw_page_header()

    def rectangle(self, x, y, width, height, color, stroke=None):
        r, g, b = color
        command = f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re"
        if stroke:
            sr, sg, sb = stroke
            self.commands.append(command + f"\n{sr:.3f} {sg:.3f} {sb:.3f} RG 0.7 w B")
        else:
            self.commands.append(command + " f")

    def circle(self, cx, cy, radius, color):
        points = [(cx + radius * math.cos(2 * math.pi * i / 48), cy + radius * math.sin(2 * math.pi * i / 48)) for i in range(49)]
        self.polygon(points, color)

    def polygon(self, points, color):
        if not points:
            return
        r, g, b = color
        commands = [f"{r:.3f} {g:.3f} {b:.3f} rg", f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        commands.extend(f"{x:.2f} {y:.2f} l" for x, y in points[1:])
        commands.append("h f")
        self.commands.append(" ".join(commands))

    def ensure_page(self, needed=22):
        if not self.pages or self.y < 38 + needed:
            self._new_page()

    @staticmethod
    def _safe(value):
        return str(value if value is not None else "").replace("\r", " ").replace("\n", " ").encode("cp1252", "replace").decode("cp1252")

    def text(self, x, y, value, size=9, bold=False, color=(0.12, 0.15, 0.2)):
        value = self._safe(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        font = "F2" if bold else "F1"
        r, g, b = color
        self.commands.append(f"BT /{font} {size} Tf {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {x:.2f} {y:.2f} Tm ({value}) Tj ET")

    def rule(self, x1, y, x2, color=(0.72, 0.77, 0.82)):
        r, g, b = color
        self.commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG 0.5 w {x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S")

    def heading(self, title):
        self.ensure_page(38)
        self.text(38, self.y, title, 13, True, (0.08, 0.25, 0.42))
        self.y -= 8
        self.rule(38, self.y, self.width-38)
        self.y -= 16

    def profile_card(self, full_name, fields):
        x, width, height = 38, self.width-76, 242
        self.ensure_page(height+30)
        top = self.y
        bottom = top-height
        self.text(x+14, top-21, "STUDENT INFORMATION", 8, True, (0.08, 0.35, 0.58))
        self.text(x+14, top-54, full_name, 16, True, (0.07, 0.20, 0.34))
        self.rule(x+14, top-66, x+width-14)
        col_width = (width-42)/2
        row_height = 33
        for index, (label, value) in enumerate(fields):
            col, row = index//5, index%5
            fx = x+16+col*(col_width+10)
            fy = top-88-row*row_height
            self.text(fx, fy, label.upper(), 6.5, True, (0.37, 0.45, 0.55))
            self.text(fx, fy-12, self._safe(value) or "Not provided", 9, color=(0.08, 0.12, 0.18))
            if row < 4:
                self.rule(fx, fy-18, fx+col_width-8, (0.88, 0.90, 0.93))
        self.y = bottom-23

    def paragraph(self, label, value):
        self.ensure_page(24)
        value = self._safe(value) or "Not provided"
        self.text(44, self.y, label + ":", 9, True)
        max_chars = max(22, int((self.width-170)/5.2))
        lines = textwrap.wrap(value, max_chars) or [""]
        self.text(160, self.y, lines[0], 9)
        self.y -= 19
        for line in lines[1:]:
            self.ensure_page(14)
            self.text(160, self.y, line, 9)
            self.y -= 19

    def table(self, headers, rows, widths, font=7.5):
        left, right = 38, self.width-38
        positions = [left]
        for fraction in widths:
            positions.append(positions[-1] + (right-left)*fraction)
        def draw_row(values, header=False, repeat_header=True):
            nonlocal positions
            wrapped = []
            for val, w in zip(values, widths):
                chars = max(5, int(((right-left)*w)/(font*0.53)))
                wrapped.append(textwrap.wrap(self._safe(val), chars) or [""])
            height = max(21, max(map(len, wrapped))*11+9)
            needs_page = not self.pages or self.y < 38 + height + 18
            if needs_page:
                self._new_page()
                if not header and repeat_header:
                    draw_row(headers, True, False)
            if header:
                self.commands.append(f"0.90 0.94 0.97 rg {left} {self.y-6} {right-left} 19 re f")
            for col, lines in enumerate(wrapped):
                for ix, line in enumerate(lines):
                    self.text(positions[col]+4, self.y-ix*10.5, line, font, header)
            self.rule(left, self.y-height+5, right)
            self.y -= height
        draw_row(headers, True)
        for row in rows:
            draw_row(row)

    def render(self):
        if not self.pages:
            self._new_page()
        objects = [None]
        def add(obj):
            objects.append(obj)
            return len(objects)-1
        catalog_id = add("")
        pages_id = add("")
        font_regular = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        image_id = None
        watermark_state_id = None
        if self.watermark:
            image = self.watermark
            image_id = add(
                f"<< /Type /XObject /Subtype /Image /Width {image['width']} /Height {image['height']} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                f"/Length {len(image['data'])} >>\nstream\n".encode("ascii") + image["data"] + b"\nendstream"
            )
            opacity = image["opacity"]
            watermark_state_id = add(f"<< /Type /ExtGState /ca {opacity:.3f} /CA {opacity:.3f} >>")
        page_ids = []
        for cmds in self.pages:
            content = ("\n".join(cmds)).encode("cp1252", "replace")
            content_id = add(f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
            resources = f"/Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >>"
            if image_id:
                resources += f" /XObject << /Logo {image_id} 0 R >> /ExtGState << /Watermark {watermark_state_id} 0 R >>"
            page_id = add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {self.width} {self.height}] /Resources << {resources} >> /Contents {content_id} 0 R >>")
            page_ids.append(page_id)
        objects[pages_id] = f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] /Count {len(page_ids)} >>"
        objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>"
        out = bytearray(b"%PDF-1.4\n% clinic report\n")
        offsets = [0]
        for index, obj in enumerate(objects[1:], 1):
            offsets.append(len(out))
            out.extend(f"{index} 0 obj\n".encode("ascii"))
            out.extend(obj if isinstance(obj, bytes) else obj.encode("latin1"))
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(objects)}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        out.extend(f"trailer\n<< /Size {len(objects)} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
        return bytes(out)


def pdf_response(document, filename, inline=False):
    response = HttpResponse(document.render(), content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


def today_label():
    return timezone.localdate().strftime("%B %d, %Y")
