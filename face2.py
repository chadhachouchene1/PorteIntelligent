#!/usr/bin/env python

import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import time
import cv2
import numpy as np
import face_recognition
import os
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import firebase_admin
from firebase_admin import credentials, db
import threading

# Configuration des GPIO
BUZZER_PIN = 23  # Remplacer par le pin GPIO de votre buzzer
DOOR_PIN = 18  # Remplacer par le pin GPIO du mécanisme de porte
PIR_PIN = 17  # Pin pour le capteur PIR (mouvement)

GPIO.setmode(GPIO.BCM)
GPIO.setup(DOOR_PIN, GPIO.OUT)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.setup(PIR_PIN, GPIO.IN)  # Capteur PIR
GPIO.output(DOOR_PIN, GPIO.LOW)  # Assurez-vous que la porte est fermée au début

# Initialiser le lecteur RFID
reader = SimpleMFRC522()

# Initialisation Firebase
cred = credentials.Certificate("/home/pi/Desktop/face_rec/firebase_admin_sdk.json")
firebase_admin.initialize_app(cred, {'databaseURL': 'https://porte-2ee6a-default-rtdb.firebaseio.com/'})

# UID RFID prédéfini
PRESET_UID = 84544912388

# Variables pour gérer l'état de la porte et le cooldown
door_opened = False
cooldown_active = False
cooldown_duration = 5  # Durée du cooldown
unknown_start_time = None
camera_active = False  # Etat de la caméra

# Fonction pour écouter Firebase et ouvrir la porte via Firebase
def listen_to_firebase():
    def listener(event):
        try:
            if event.data == 1 and not door_opened:
                print("Firebase triggered door open.")
                open_door()
        except Exception as e:
            print(f"Error in Firebase listener: {e}")

    # Écouter les changements dans le champ 'status' de Firebase
    ref = db.reference('status/status')
    ref.listen(listener)

# Fonction pour mettre à jour le statut dans Firebase
def update_status_in_firebase(status):
    ref = db.reference('status/status')
    ref.set(status)
    print(f"Firebase status updated to: {status}")

def update_logs_in_firebase(user, time):
    ref = db.reference('status/user')
    ref.set(user)
    ref = db.reference('status/time')
    ref.set(time)

# Fonction pour envoyer un email avec une image
def send_email(image_path):
    sender_email = "facerec.pfe@gmail.com"
    sender_password = "pqydpvbjscasonny"
    receiver_email = "chouchenechadha01@gmail.com"
    subject = "Unknown Face Detected"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject

    text = "An unknown face has been detected. Please see the attached image."
    message.attach(MIMEText(text, "plain"))

    with open(image_path, "rb") as file:
        image_data = file.read()
        image = MIMEImage(image_data, name="UnknownFace.jpg")
        message.attach(image)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, message.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print("Failed to send email.")
        print(str(e))

# Charger les visages connus pour la reconnaissance faciale
path = 'authorized'
images = []
classNames = []
myList = os.listdir(path)
for cl in myList:
    curImg = cv2.imread(f'{path}/{cl}')
    if curImg is not None:
        images.append(curImg)
        classNames.append(os.path.splitext(cl)[0])

# Encoder les visages connus
def findEncoding(images):
    encodeList = []
    for img in images:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(img)
        if face_locations:
            encode = face_recognition.face_encodings(img, face_locations)[0]
            encodeList.append(encode)
    return encodeList

encodeListknown = findEncoding(images)
print('Face encoding complete')

# Fonction pour faire bip avec le buzzer
def buzzer_beep(beeps, duration=0.3, delay=0.2):
    for _ in range(beeps):
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(delay)

# Fonction pour marquer l'attendance
def markAttendance(name):
    with open('Attendance.csv', 'r+') as f:
        myDataList = f.readlines()
        nameList = [entry.split(',')[0] for entry in myDataList]
        now = datetime.now()
        dtString = now.strftime('%H:%M:%S')
        f.writelines(f'\n{name},{dtString}')
        update_logs_in_firebase(name, dtString)

# Fonction pour ouvrir la porte
def open_door():
    global door_opened
    if not door_opened:
        print("Door opened")
        buzzer_beep(1)
        GPIO.output(DOOR_PIN, GPIO.HIGH)
        door_opened = True
        update_status_in_firebase(1)
        time.sleep(5)  # Garder la porte ouverte pendant 5 secondes
        GPIO.output(DOOR_PIN, GPIO.LOW)
        print("Door closed")
        update_status_in_firebase(0)
        door_opened = False
    else:
        print("Door is already opened, waiting for it to close.")

# Logique RFID
def handle_rfid():
    while True:
        try:
            print("Tap the card")
            id, _ = reader.read()
            print(f"RFID UID: {id}")
            if id == PRESET_UID and not door_opened:
                open_door()
            else:
                print("Unauthorized UID detected!")
                buzzer_beep(3)  # Triple bip pour accès non autorisé
        except Exception as e:
            print(f"RFID error: {e}")

# Logique de reconnaissance faciale
def handle_face_recognition():
    global cooldown_active, unknown_start_time, camera_active
    cap = cv2.VideoCapture(0)  # Initialiser la caméra
    while True:
        if camera_active:
            success, img = cap.read()
            if not success:
                print("Échec de la capture d'image.")
                continue

            imgS = cv2.resize(img, (0, 0), None, 0.25, 0.25)
            imgS = cv2.cvtColor(imgS, cv2.COLOR_BGR2RGB)

            # Ignorer la détection si le cooldown est actif
            if cooldown_active:
                cv2.imshow('Webcam', img)
                cv2.waitKey(1)
                continue

            facesCurFrame = face_recognition.face_locations(imgS)
            encodeCurFrame = face_recognition.face_encodings(imgS, facesCurFrame)

            for encodeFace, faceLoc in zip(encodeCurFrame, facesCurFrame):
                matches = face_recognition.compare_faces(encodeListknown, encodeFace)
                faceDis = face_recognition.face_distance(encodeListknown, encodeFace)
                matchIndex = np.argmin(faceDis)

                if matches[matchIndex] and not door_opened:
                    name = classNames[matchIndex].upper()
                    markAttendance(name)
                    open_door()

                    # Activer le cooldown
                    cooldown_active = True
                    threading.Timer(cooldown_duration, reset_cooldown).start()

                else:
                    if unknown_start_time is None:
                        unknown_start_time = time.time()  # Démarrer le chronomètre lorsque le visage inconnu est détecté

                    elapsed_time = time.time() - unknown_start_time
                    if elapsed_time >= 5:  # Si le visage inconnu est détecté pendant 5 secondes
                        now = datetime.now()
                        img_name = now.strftime("%Y%m%d_at_%H%M%S") + ".jpg"
                        img_path = os.path.join("unknown_faces", img_name)
                        cv2.imwrite(img_path, img)
                        send_email(img_path)
                        print("Visage inconnu détecté pendant 5 secondes... Email envoyé!")
                        buzzer_beep(3)
                        unknown_start_time = None  # Réinitialiser le chronomètre après l'envoi de l'email

                    name = "Inconnu"
                    y1, x2, y2, x1 = faceLoc
                    y1, x2, y2, x1 = y1 * 4, x2 * 4, y2 * 4, x1 * 4
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.rectangle(img, (x1, y2 - 35), (x2, y2), (0, 0, 255), cv2.FILLED)
                    cv2.putText(img, name, (x1 + 6, y2 - 6), cv2.FONT_HERSHEY_COMPLEX, 1, (255, 255, 255), 2)

            cv2.imshow('Webcam', img)
            cv2.waitKey(1)
        else:
            # Si aucun mouvement n'est détecté, la caméra n'est pas utilisée
            cv2.imshow('Webcam', np.zeros((480, 640, 3), np.uint8))  # Affiche une image noire ou vide
            cv2.waitKey(1)

# Fonction pour réinitialiser le cooldown
def reset_cooldown():
    global cooldown_active
    cooldown_active = False
    print("Cooldown reset. Ready for new detections.")

# Fonction pour gérer la détection de mouvement
def handle_motion_detection():
    global camera_active
    while True:
        if GPIO.input(PIR_PIN):  # Si mouvement détecté
            if not camera_active:
                print("Mouvement détecté, caméra activée.")
                camera_active = True
        else:
            if camera_active:
                print("Aucun mouvement détecté, caméra désactivée.")
                camera_active = False
        
        time.sleep(0.1)  # Attendre un peu avant de vérifier à nouveau

# Programme principal
try:
    access_granted = False

    # Créer des threads pour RFID, reconnaissance faciale, Firebase et le capteur PIR
    rfid_thread = threading.Thread(target=handle_rfid, daemon=True)
    face_thread = threading.Thread(target=handle_face_recognition, daemon=True)
    firebase_thread = threading.Thread(target=listen_to_firebase, daemon=True)
    pir_thread = threading.Thread(target=handle_motion_detection, daemon=True)  # Thread pour capteur PIR

    # Démarrer les threads
    rfid_thread.start()
    face_thread.start()
    firebase_thread.start()
    pir_thread.start()

    # Garder le programme principal en cours d'exécution
    while True:
        time.sleep(0.1)

finally:
    GPIO.cleanup()
    cv2.destroyAllWindows()
