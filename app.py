from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# Chemin vers le répertoire où les images seront sauvegardées
SAVE_DIR = os.path.expanduser("/home/pi/Desktop/face_rec/authorized")
os.makedirs(SAVE_DIR, exist_ok=True)  # Crée le répertoire s'il n'existe pas


@app.route('/upload', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "No image file in request"}), 400

    file = request.files['image']

    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Vérification stricte pour les fichiers .png
    if not file.filename.lower().endswith('.png'):
        return jsonify({"error": "Invalid file type. Only PNG files are allowed"}), 400

    try:
        save_path = os.path.join(SAVE_DIR, file.filename)
        file.save(save_path)
        return jsonify({"message": f"Image saved to {save_path}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
