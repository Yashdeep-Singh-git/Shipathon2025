import streamlit as st
import google.generativeai as gemini
from docx import Document
from groq import Groq
from dotenv import load_dotenv
import tempfile
import io
import os
from streamlit_webrtc import webrtc_streamer
import av
import numpy as np
import wave
import queue

# Load environment variables
load_dotenv()

GROQ_API_KEY = st.secrets["groqkey"]
GEMINI_API_KEY = st.secrets["key"]

# Configure Gemini
gemini.configure(api_key=GEMINI_API_KEY)

class AudioProcessor:
    def __init__(self):
        self.frames = []
        self.recording = False
        
    def process_audio(self, frame):
        if self.recording:
            sound = frame.to_ndarray()
            sound = sound.astype(np.int16)
            self.frames.append(sound)
        return frame

    def save_audio(self, filename):
        if not self.frames:
            return False
            
        # Convert to wav format
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            for frame in self.frames:
                wf.writeframes(frame.tobytes())
        return True

def transcribe_audio(file_path):
    """Transcribe audio using Groq"""
    client = Groq(api_key=GROQ_API_KEY)
    
    with open(file_path, "rb") as file:
        transcription = client.audio.transcriptions.create(
            file=(file_path, file.read()),
            model="whisper-large-v3-turbo",
            prompt="use full stops where necessary",
            response_format="json",
            language="en",
            temperature=0.0
        )
    return transcription.text

def generate_notes(text):
    """Generate notes using Gemini"""
    model = gemini.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(
        "write notes with headings and numbering (and write headings on different line): " + text
    )
    return response.text

def create_formatted_doc(text):
    """Create and format a Word document"""
    doc = Document()
    paragraph = doc.add_paragraph(text)
    
    # Format text (bold and underline between **)
    for paragraph in doc.paragraphs:
        text = paragraph.text
        runs_to_add = []
        
        while "**" in text:
            start = text.find("**")
            end = text.find("**", start + 2)
            
            if end == -1:
                break
            if start > 0:
                runs_to_add.append((text[:start], False))
            runs_to_add.append((text[start + 2:end], True))
            text = text[end + 2:]
        if text:
            runs_to_add.append((text, False))
            
        for run in paragraph.runs:
            run.text = ""
        for content, is_bold in runs_to_add:
            run = paragraph.add_run(content)
            run.bold = is_bold
            run.underline = is_bold
    
    # Save to bytes buffer
    doc_buffer = io.BytesIO()
    doc.save(doc_buffer)
    doc_buffer.seek(0)
    return doc_buffer

def main():
    st.title("Audio to Notes Converter")
    
    # Initialize session state
    if 'audio_processor' not in st.session_state:
        st.session_state.audio_processor = AudioProcessor()
    if 'notes' not in st.session_state:
        st.session_state.notes = None
    if 'doc_buffer' not in st.session_state:
        st.session_state.doc_buffer = None
    
    # File name input
    file_name = st.text_input("Enter name for your file:", "my_notes")
    
    # Audio recording interface
    st.subheader("Audio Recording")
    
    webrtc_ctx = webrtc_streamer(
        key="audio-recorder",
        mode=webrtc_streamer.AUDIO_ONLY,
        audio_processor_factory=lambda: st.session_state.audio_processor,
        rtc_configuration={
            "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
        }
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Start Recording", disabled=webrtc_ctx.state.playing and st.session_state.audio_processor.recording):
            st.session_state.audio_processor.recording = True
            st.session_state.audio_processor.frames = []
            st.rerun()
    
    with col2:
        if st.button("Stop Recording", disabled=not (webrtc_ctx.state.playing and st.session_state.audio_processor.recording)):
            st.session_state.audio_processor.recording = False
            
            # Create temporary file for audio
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
                if st.session_state.audio_processor.save_audio(temp_audio.name):
                    try:
                        with st.spinner("Transcribing audio..."):
                            transcribed_text = transcribe_audio(temp_audio.name)
                            st.info("Transcription complete!")
                        
                        with st.spinner("Generating notes..."):
                            notes = generate_notes(transcribed_text)
                            st.session_state.notes = notes
                            st.info("Notes generated!")
                        
                        # Create document
                        st.session_state.doc_buffer = create_formatted_doc(notes)
                        
                    except Exception as e:
                        st.error(f"Error processing audio: {e}")
                    finally:
                        os.unlink(temp_audio.name)
            st.rerun()
    
    # Recording status indicator
    if webrtc_ctx.state.playing and st.session_state.audio_processor.recording:
        st.markdown("🔴 **Recording in progress...**")
    
    # Display notes if available
    if st.session_state.notes:
        st.subheader("Generated Notes")
        st.text(st.session_state.notes)
        
        # Download button
        if st.session_state.doc_buffer:
            st.download_button(
                label="Download Word Document",
                data=st.session_state.doc_buffer,
                file_name=f"{file_name}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

if __name__ == "__main__":
    main()
