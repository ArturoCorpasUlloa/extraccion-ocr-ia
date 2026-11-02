import os
import io
import json
import time
import threading
import queue
import pandas as pd
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import google.generativeai as genai

# =========================
# 🔥 CONFIGURACIÓN
# =========================
# Configura GEMINI_API_KEY en el entorno; nunca guardes la llave en este archivo.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Configuración de rutas locales
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = os.environ.get("POPPLER_PATH", "").strip() or None

# Calidad de imagen para OCR
DPI = 300 

# Configurar la IA
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# =========================
# LÓGICA DE IA (GEMINI)
# =========================
def procesar_texto_con_ia(texto_sucio):
    if not texto_sucio.strip():
        return []

    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Analiza el texto de OCR de una orden médica y extrae:
    - orden: Número de autorización.
    - documento: ID del paciente.
    - diagnostico: Código CIE-10.
    - codigo: Código del servicio.
    - cantidad: Cantidad.
    - nombre_servicio: Nombre del examen.

    Devuelve un JSON con el formato: {{"datos": [{{...}}]}}
    No escribas nada más que el JSON.

    TEXTO:
    {texto_sucio}
    """

    try:
        response = model.generate_content(prompt)
        respuesta_texto = response.text.strip()
        
        if "```json" in respuesta_texto:
            respuesta_texto = respuesta_texto.split("```json")[1].split("```")[0].strip()
        elif "```" in respuesta_texto:
            respuesta_texto = respuesta_texto.split("```")[1].split("```")[0].strip()

        resultado = json.loads(respuesta_texto)
        return resultado.get("datos", [])
    except Exception as e:
        print(f"Error procesando con IA: {e}")
        return []

# =========================
# LÓGICA DE OCR
# =========================
def obtener_texto_de_pdf(ruta_pdf, callback_log):
    try:
        paginas = convert_from_path(ruta_pdf, dpi=DPI, poppler_path=POPPLER_PATH)
        texto_completo = ""
        for i, pag in enumerate(paginas):
            callback_log(f"    - OCR página {i+1}...")
            img = pag.convert("L")
            texto_pag = pytesseract.image_to_string(img, lang="spa", config="--psm 3")
            texto_completo += texto_pag + "\n"
        return texto_completo
    except Exception as e:
        callback_log(f"    - ❌ Error en OCR: {e}")
        return ""

# =========================
# INTERFAZ GRÁFICA (UI)
# =========================
class AppExtractorIA:
    def __init__(self, root):
        self.root = root
        self.root.title("Extractor Médico IA Gratis (Gemini)")
        self.root.geometry("600x500")
        self.queue = queue.Queue()
        self._setup_ui()
        self.root.after(100, self._process_queue)

    def _setup_ui(self):
        frame = ttk.Frame(self.root, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Carpeta con PDFs escaneados:", font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.txt_carpeta = ttk.Entry(frame)
        self.txt_carpeta.pack(fill=tk.X, pady=5)
        
        btn_sel = ttk.Button(frame, text="📁 Seleccionar Carpeta", command=self._seleccionar_carpeta)
        btn_sel.pack(anchor=tk.E)

        self.btn_run = ttk.Button(frame, text="🚀 INICIAR PROCESAMIENTO", command=self._iniciar)
        self.btn_run.pack(pady=20)

        self.log_widget = tk.Text(frame, height=12, state=tk.DISABLED, font=("Consolas", 9))
        self.log_widget.pack(fill=tk.BOTH, expand=True)

    def _seleccionar_carpeta(self):
        path = filedialog.askdirectory()
        if path:
            self.txt_carpeta.delete(0, tk.END)
            self.txt_carpeta.insert(0, path)

    def _log(self, msg):
        self.queue.put(msg)

    def _process_queue(self):
        while not self.queue.empty():
            msg = self.queue.get()
            self.log_widget.config(state=tk.NORMAL)
            self.log_widget.insert(tk.END, f"{msg}\n")
            self.log_widget.see(tk.END)
            self.log_widget.config(state=tk.DISABLED)
        self.root.after(100, self._process_queue)

    def _iniciar(self):
        carpeta = self.txt_carpeta.get()
        if not carpeta or not os.path.exists(carpeta):
            return messagebox.showerror("Error", "Carpeta no válida")
        if not GEMINI_API_KEY:
            return messagebox.showerror("Error", "Pon tu API KEY de Gemini")

        self.btn_run.config(state=tk.DISABLED)
        threading.Thread(target=self._worker, args=(carpeta,), daemon=True).start()

    def _worker(self, carpeta):
        archivos = [f for f in os.listdir(carpeta) if f.lower().endswith(".pdf")]
        if not archivos:
            self._log("❌ No hay PDFs.")
            self.root.after(0, lambda: self.btn_run.config(state=tk.NORMAL))
            return

        datos_totales = []
        for nombre_archivo in archivos:
            ruta = os.path.join(carpeta, nombre_archivo)
            self._log(f"📄 Procesando: {nombre_archivo}")
            texto_ocr = obtener_texto_de_pdf(ruta, self._log)
            if texto_ocr.strip():
                self._log("    - Interpretando con IA...")
                datos = procesar_texto_con_ia(texto_ocr)
                for d in datos: d["archivo"] = nombre_archivo
                datos_totales.extend(datos)
                self._log(f"    - ✅ Extraídos {len(datos)} registros.")

        if datos_totales:
            df = pd.DataFrame(datos_totales)
            ruta_excel = os.path.join(carpeta, "Resultados_IA.xlsx")
            df.to_excel(ruta_excel, index=False)
            self._log(f"\n🏆 TERMINADO. Guardado en: {ruta_excel}")
            # AQUÍ ESTABA EL ERROR, YA ESTÁ CORREGIDO:
            messagebox.showinfo("Finalizado", f"Se procesaron {len(archivos)} archivos.")
        else:
            self._log("\n❌ No se obtuvieron datos.")

        self.root.after(0, lambda: self.btn_run.config(state=tk.NORMAL))

if __name__ == "__main__":
    root = tk.Tk()
    app = AppExtractorIA(root)
    root.mainloop()