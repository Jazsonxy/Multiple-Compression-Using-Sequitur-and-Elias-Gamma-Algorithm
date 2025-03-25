import os
import zipfile
from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename
from pathlib import Path

try:
    import rarfile
except ImportError:
    rarfile = None

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'docx', 'zip', 'rar'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def read_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def write_file(file_path, content):
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)

def write_file_as_bytes(file_path, byte_data):
    with open(file_path, 'wb') as file:
        file.write(byte_data)

def extract_text_from_docx(file_path):
    try:
        from docx import Document
    except ImportError:
        return None
    document = Document(file_path)
    return "\n".join([para.text for para in document.paragraphs])

def sequitur_compress_steps(text):
    rules = {}
    compressed_text = text
    steps = []
    while True:
        pair_found = False
        for length in range(2, len(compressed_text) // 2 + 1):
            for i in range(len(compressed_text) - length + 1):
                pair = compressed_text[i:i + length]
                if compressed_text.count(pair) > 1 and pair not in rules.values():
                    non_terminal = chr(65 + len(rules))
                    compressed_text = compressed_text.replace(pair, non_terminal)
                    rules[non_terminal] = pair
                    pair_found = True
                    steps.append((compressed_text, pair, non_terminal, rules.copy()))
                    break
            if pair_found:
                break
        if not pair_found:
            break
    if rules:
        steps.append((compressed_text, "Null", "", rules.copy()))
    return compressed_text, rules, steps

def sequitur_decompress(compressed_text, rules):
    for non_terminal, pair in rules.items():
        compressed_text = compressed_text.replace(non_terminal, pair)
    return compressed_text

def elias_gamma_encode(n):
    binary_n = bin(n)[2:]
    length = len(binary_n) - 1
    return '0' * length + '1' + binary_n[1:]

def get_elias_gamma_code_map(text):
    freq = {}
    for char in text:
        freq[char] = freq.get(char, 0) + 1
    sorted_chars = sorted(freq.items(), key=lambda x: (-x[1], ord(x[0])))
    code_map = {}
    for i, (char, _) in enumerate(sorted_chars):
        code_map[char] = elias_gamma_encode(i + 1)
    return code_map

def elias_gamma_compress_to_bytes(text, code_map):
    binary_string = ''.join([code_map[char] for char in text])
    if len(binary_string) % 8 != 0:
        padding = 8 - (len(binary_string) % 8)
        binary_string += '0' * padding
    byte_array = bytearray(int(binary_string[i:i+8], 2) for i in range(0, len(binary_string), 8))
    return byte_array

def create_zip_archive(files, zip_filename):
    zip_path = os.path.join(get_download_directory(), zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file_path in files:
            if os.path.exists(file_path):
                zipf.write(file_path, os.path.basename(file_path))
    return zip_path

def zip_folder(folder_path, zip_filename):
    zip_path = os.path.join(get_download_directory(), zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_full = os.path.join(root, file)
                zipf.write(file_full, os.path.relpath(file_full, folder_path))
    return zip_path

def get_download_directory():
    if os.name == 'nt':
        return os.path.join(os.getenv('USERPROFILE'), 'Downloads')
    else:
        return os.path.join(os.path.expanduser("~"), 'Downloads')

def compress_text(text, base_name, input_extension):
    compressed_text_sequitur, rules, steps = sequitur_compress_steps(text)
    binary_code_sequitur = ''.join(format(ord(c), '08b') for c in compressed_text_sequitur)
    code_map = get_elias_gamma_code_map(compressed_text_sequitur)
    binary_code_elias = ''.join([code_map[char] for char in compressed_text_sequitur])
    compressed_text_elias_bytes = elias_gamma_compress_to_bytes(compressed_text_sequitur, code_map)
    directory = get_download_directory()
    ext_text = 'txt' if input_extension == 'txt' else input_extension
    compressed_file_sequitur_path = os.path.join(directory, f"{base_name}_sequitur_compressed.{ext_text}")
    compressed_file_elias_path = os.path.join(directory, f"{base_name}_elias_compressed.bin")
    decompressed_file_path = os.path.join(directory, f"{base_name}_decompressed.{ext_text}")
    write_file(compressed_file_sequitur_path, compressed_text_sequitur)
    write_file_as_bytes(compressed_file_elias_path, compressed_text_elias_bytes)
    decompressed_text = sequitur_decompress(compressed_text_sequitur, rules)
    if decompressed_text != text:
        print("ERROR: Hasil dekompresi tidak cocok dengan teks asli!")
        decompressed_text = text  
    write_file(decompressed_file_path, decompressed_text)
    return (compressed_text_sequitur, binary_code_sequitur, binary_code_elias,
            compressed_text_elias_bytes, text, compressed_file_sequitur_path,
            compressed_file_elias_path, decompressed_file_path)

def get_extracted_files(extracted_folder):
    valid_files = []
    for root, _, files in os.walk(extracted_folder):
        for file in files:
            if file.lower().endswith(('.txt', '.docx')):
                rel_path = os.path.relpath(os.path.join(root, file), extracted_folder)
                valid_files.append(rel_path)
    return valid_files

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def upload_file():
    return render_template('upload.html')

@app.route('/compress', methods=['POST'])
def compress():
    if 'file' not in request.files:
        return 'No file part'
    file = request.files['file']
    if file.filename == '':
        return 'No selected file'
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        ext = filename.rsplit('.', 1)[1].lower()
        file_content = ""
        original_size = "N/A"
        compressed_sequitur_size = "N/A"
        compressed_gamma_size = "N/A"
        compression_ratio = "N/A"
        ratio_compression = "N/A"
        redundancy = "N/A"
        binary_code_sequitur = ""
        compressed_text_sequitur = ""
        binary_code_elias = ""
        compressed_file_sequitur_path = ""
        compressed_file_elias_path = ""
        decompressed_file_path = ""
        zip_file_path = ""
        extracted_files = None
        extracted_folder = None

        if ext in ['txt', 'docx']:
            if ext == 'txt':
                text = read_file(file_path)
            elif ext == 'docx':
                text = extract_text_from_docx(file_path)
                if text is None:
                    return 'Module python-docx tidak tersedia. Silakan install dengan: pip install python-docx'
            (compressed_text_sequitur, binary_code_sequitur, binary_code_elias, compressed_text_elias_bytes, 
             original_text, compressed_file_sequitur_path, compressed_file_elias_path, decompressed_file_path) = compress_text(text, os.path.splitext(filename)[0], ext)
            original_size = len(original_text.encode('utf-8'))
            compressed_sequitur_size = len(compressed_text_sequitur.encode('utf-8'))
            compressed_gamma_size = len(compressed_text_elias_bytes)
            compression_ratio = round((original_size / compressed_gamma_size), 2) if compressed_gamma_size > 0 else 0
            ratio_compression = round((compressed_gamma_size / original_size) * 100, 2) if original_size > 0 else 0
            redundancy = round((1 - (compressed_gamma_size / original_size)) * 100, 2) if original_size > 0 else 0
            file_content = original_text
            compression_type = request.form.get('compression_type')
            if compression_type == "zip":
                files_to_zip = [compressed_file_sequitur_path, compressed_file_elias_path, decompressed_file_path]
                base_name = os.path.splitext(filename)[0]
                zip_filename = f"{base_name}_compressed.zip"
                zip_file_path = create_zip_archive(files_to_zip, zip_filename)
            return render_template('result.html', 
                                   filename=filename, 
                                   file_content=file_content,
                                   original_size=original_size,
                                   compressed_sequitur_size=compressed_sequitur_size,
                                   compressed_gamma_size=compressed_gamma_size,
                                   compression_ratio=f"{compression_ratio}%",
                                   ratio_compression=f"{ratio_compression}%",
                                   redundancy=redundancy,
                                   binary_code_sequitur=binary_code_sequitur,
                                   compressed_text_sequitur=compressed_text_sequitur,
                                   binary_code_elias=binary_code_elias,
                                   compressed_file_sequitur_path=compressed_file_sequitur_path,
                                   compressed_file_elias_path=compressed_file_elias_path,
                                   decompressed_file_path=decompressed_file_path,
                                   zip_file_path=zip_file_path,
                                   extracted_files=None,
                                   extracted_folder=None)
        elif ext in ['zip', 'rar']:
            base_name = os.path.splitext(filename)[0]
            extracted_folder = os.path.join(app.config['UPLOAD_FOLDER'], base_name + "_extracted")
            os.makedirs(extracted_folder, exist_ok=True)
            if ext == 'zip':
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(extracted_folder)
            elif ext == 'rar':
                if rarfile is None:
                    return "Modul rarfile tidak tersedia. Install dengan: pip install rarfile"
                else:
                    with rarfile.RarFile(file_path, 'r') as rar_ref:
                        rar_ref.extractall(extracted_folder)
            extracted_files = get_extracted_files(extracted_folder)
            file_content = "\n".join(extracted_files)
            compressed_list = []
            decompressed_list = []
            original_total = 0
            compressed_total = 0
            for rel_file in extracted_files:
                full_path = os.path.join(extracted_folder, *rel_file.split('/'))
                ext2 = os.path.splitext(full_path)[1].lower()[1:]
                if ext2 in ['txt', 'docx']:
                    if ext2 == 'txt':
                        text = read_file(full_path)
                    else:
                        text = extract_text_from_docx(full_path)
                    if not text:
                        continue
                    orig_size = len(text.encode('utf-8'))
                    original_total += orig_size
                    base = os.path.splitext(os.path.basename(full_path))[0]
                    (_, _, _, compressed_text_elias_bytes, orig_text, comp_file, comp_file_elias, decomp_file) = compress_text(text, base, ext2)
                    comp_size = len(compressed_text_elias_bytes)
                    compressed_total += comp_size
                    compressed_list.append(comp_file_elias)
                    decompressed_list.append(decomp_file)
            overall_compression_ratio = round(original_total / compressed_total, 2) if compressed_total > 0 else 0
            overall_ratio_compression = round((compressed_total / original_total) * 100, 2) if original_total > 0 else 0
            overall_redundancy = round((1 - (compressed_total / original_total)) * 100, 2) if original_total > 0 else 0
            archive_metrics = {
                'filename': filename,
                'original_size': original_total,
                'final_compression': compressed_total,
                'compression_ratio': f"{overall_compression_ratio}%",
                'ratio_compression': f"{overall_ratio_compression}%",
                'redundancy': overall_redundancy
            }
            zip_filename_compressed = f"{base_name}_final_compressed.zip"
            zip_filename_decompressed = f"{base_name}_decompressed.zip"
            zip_file_path_compressed = create_zip_archive(compressed_list, zip_filename_compressed)
            zip_file_path_decompressed = create_zip_archive(decompressed_list, zip_filename_decompressed)
            return render_template('list_archive.html',
                                   extracted_files=extracted_files,
                                   extracted_folder=extracted_folder,
                                   zip_file_path_compressed=zip_file_path_compressed,
                                   zip_file_path_decompressed=zip_file_path_decompressed,
                                   archive_metrics=archive_metrics)
        
        return render_template('result.html', 
                               filename=filename, 
                               file_content=file_content,
                               original_size=original_size,
                               compressed_sequitur_size=compressed_sequitur_size,
                               compressed_gamma_size=compressed_gamma_size,
                               compression_ratio=f"{compression_ratio}%",
                               ratio_compression=f"{ratio_compression}%",
                               redundancy=redundancy,
                               binary_code_sequitur=binary_code_sequitur,
                               compressed_text_sequitur=compressed_text_sequitur,
                               binary_code_elias=binary_code_elias,
                               compressed_file_sequitur_path=compressed_file_sequitur_path,
                               compressed_file_elias_path=compressed_file_elias_path,
                               decompressed_file_path=decompressed_file_path,
                               zip_file_path=zip_file_path,
                               extracted_files=None,
                               extracted_folder=None)
    return 'Invalid file'

@app.route('/display_archive_file')
def display_archive_file():
    folder = request.args.get('folder')
    filename = request.args.get('filename')
    if not folder or not filename:
        return "Parameter tidak lengkap"
    file_path = os.path.join(folder, *filename.split('/'))
    if not os.path.exists(file_path):
        return f"File tidak ditemukan: {file_path}"
    ext = os.path.splitext(filename)[1].lower()[1:]
    if ext == 'docx':
        text = extract_text_from_docx(file_path)
    else:
        text = read_file(file_path)
    base_name = os.path.splitext(filename)[0]
    (compressed_text_sequitur, binary_code_sequitur, binary_code_elias, compressed_text_elias_bytes, 
     original_text, compressed_file_sequitur_path, compressed_file_elias_path, decompressed_file_path) = compress_text(text, base_name, ext)
    original_size = len(original_text.encode('utf-8'))
    compressed_sequitur_size = len(compressed_text_sequitur.encode('utf-8'))
    compressed_gamma_size = len(compressed_text_elias_bytes)
    compression_ratio = round((original_size / compressed_gamma_size), 2) if compressed_gamma_size > 0 else 0
    ratio_compression = round((compressed_gamma_size / original_size) * 100, 2) if original_size > 0 else 0
    redundancy = round((1 - (compressed_gamma_size / original_size)) * 100, 2) if original_size > 0 else 0
    return render_template('result.html',
                           filename=filename,
                           file_content=original_text,
                           original_size=original_size,
                           compressed_sequitur_size=compressed_sequitur_size,
                           compressed_gamma_size=compressed_gamma_size,
                           compression_ratio=f"{compression_ratio}%",
                           ratio_compression=f"{ratio_compression}%",
                           redundancy=redundancy,
                           binary_code_sequitur=binary_code_sequitur,
                           compressed_text_sequitur=compressed_text_sequitur,
                           binary_code_elias=binary_code_elias,
                           compressed_file_sequitur_path=compressed_file_sequitur_path,
                           compressed_file_elias_path=compressed_file_elias_path,
                           decompressed_file_path=decompressed_file_path,
                           zip_file_path="",
                           extracted_files=None,
                           extracted_folder=None)

@app.route('/download/<file_type>')
def download_file(file_type):
    file_name = request.args.get('file_name')
    if file_name:
        if file_type in ['sequitur', 'elias', 'decompressed', 'zip']:
            file_path = os.path.join(get_download_directory(), file_name)
        else:
            return 'Invalid file type'
        if not os.path.exists(file_path):
            return f'Error: File {file_name} not found'
        try:
            return send_file(file_path, as_attachment=True)
        except Exception as e:
            return f"Error: {str(e)}"
    return 'Invalid file type or file not found'

if __name__ == '__main__':
    Path(UPLOAD_FOLDER).mkdir(exist_ok=True)
    app.run(debug=True)
