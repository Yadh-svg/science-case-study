"""
Streamlit Question Generator Application
A modern UI for generating educational questions across multiple topics and types.
"""
import streamlit as st
import yaml
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
from st_img_pastebutton import paste
import io
import base64
import re
from duplication_handler import process_parallel_duplication

class PastedFile(io.BytesIO):
    """Wrapper to make pasted images look like UploadedFile objects"""
    def __init__(self, content, name="pasted_image.png", type="image/png"):
        if isinstance(content, str):
            if content.startswith("data:"):
                # Handle Data URI (e.g., data:image/png;base64,...)
                try:
                    header, encoded = content.split(",", 1)
                    content = base64.b64decode(encoded)
                    # Try to extract type from header
                    if "image/" in header:
                        type_match = re.search(r"image/(\w+)", header)
                        if type_match:
                            type = f"image/{type_match.group(1)}"
                            ext = type_match.group(1)
                            if not name.endswith(f".{ext}"):
                                name = f"pasted_image.{ext}"
                except Exception:
                    # Fallback or invalid data uri
                    pass
            else:
                # Try hex (original assumption)
                try:
                    content = bytes.fromhex(content)
                except ValueError:
                    # Try raw base64 as last resort
                    try:
                        content = base64.b64decode(content)
                    except Exception:
                        pass # Keep as is if all fails (likely to error later but allow debug)

        super().__init__(content)
        self.name = name
        self.type = type
        self.size = len(content)

# Page configuration
st.set_page_config(
    page_title="AI Science Question Creator",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern, catchy UI
st.markdown("""
<style>
    /* Main theme colors */
    :root {
        --primary-color: #6366f1;
        --secondary-color: #8b5cf6;
        --success-color: #10b981;
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 700;
    }
    
    .main-header p {
        margin: 0.5rem 0 0 0;
        font-size: 1.1rem;
        opacity: 0.9;
    }
    
    /* Section headers */
    .section-header {
        background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
        color: white;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        margin: 1.5rem 0 1rem 0;
        font-weight: 600;
        font-size: 1.2rem;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.75rem 2rem;
        font-weight: 600;
        font-size: 1rem;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
    }
    
    /* Info boxes */
    .info-box {
        background: #eff6ff;
        border-left: 4px solid #3b82f6;
        padding: 1rem;
        border-radius: 4px;
        margin: 1rem 0;
    }
    
    /* Hide copy-to-clipboard buttons */
    button[title="Copy to clipboard"],
    button[data-testid="stCopyButton"],
    .copy-button,
    [data-testid="stMarkdownContainer"] button {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# Authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def check_authentication():
    """Check if user is authenticated"""
    return st.session_state.authenticated

def login(username, password):
    """Validate login credentials"""
    try:
        correct_username = st.secrets["USERNAME"]
        correct_password = st.secrets["PASSWORD"]
        if username == correct_username and password == correct_password:
            st.session_state.authenticated = True
            return True
    except Exception as e:
        st.error(f"❌ Error reading credentials: {e}")
    return False

# Show login page if not authenticated
if not check_authentication():
    st.markdown("""
    <div class="main-header">
        <h1>🔐 AI Science Question Creator</h1>
        <p>Secure Login Required</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 🔑 Login")
    
    # Create a centered login form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("🔓 Login", use_container_width=True)
            
            if submit:
                if username and password:
                    if login(username, password):
                        st.success("✅ Login successful! Redirecting...")
                        st.rerun()
                    else:
                        st.error("❌ Invalid username or password")
                else:
                    st.warning("⚠️ Please enter both username and password")
    
    st.stop()  # Stop execution here if not authenticated

# Initialize session state
if 'question_types_config' not in st.session_state:
    st.session_state.question_types_config = {}
if 'generated_output' not in st.session_state:
    st.session_state.generated_output = None
if 'universal_pdf' not in st.session_state:
    st.session_state.universal_pdf = None

# Header
st.markdown("""
<div class="main-header">
    <h1>📚 AI Science Question Creator</h1>
    <p>Generate high-quality educational questions with advanced AI</p>
</div>
""", unsafe_allow_html=True)

# Core Skill Extraction Toggle
st.markdown("### 🔧 Core Skill Extraction")
core_skill_enabled = st.checkbox(
    "Enable Core Skill Extraction",
    key="core_skill_enabled",
    help="When enabled, extracts metadata (core_equation, solution_pattern, scenario_signature, etc.) from each batch of questions and passes it to subsequent batches to ensure uniqueness and avoid duplicate scenarios."
)
if core_skill_enabled:
    st.info("✅ Core Skill enabled. Sequential processing will be used for batches of the same type to pass metadata between them.")
st.markdown("---")

# Sidebar for API configuration
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    # API key is now fetched from st.secrets for security
    try:
        gemini_api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        st.error("❌ GEMINI_API_KEY not found in secrets.toml")
        gemini_api_key = None
    
    st.markdown("---")
    st.markdown("### 📊 Statistics")
    total_q = sum(config.get('count', 0) for config in st.session_state.question_types_config.values())
    st.metric("Total Questions", total_q)
    
    if st.session_state.question_types_config:
        st.markdown("**Question Types:**")
        for qtype, config in st.session_state.question_types_config.items():
            st.write(f"• {qtype}: {config.get('count', 0)}")
    
    st.markdown("---")
    st.markdown("### 🗑️ Reset Tools")
    
    col_clr_in, col_clr_out = st.columns(2)
    with col_clr_in:
        if st.button("Clear Inputs", help="Reset all configuration inputs to default"):
            # Clear session state keys related to inputs
            # Explicitly set widget keys to empty/default to force UI update
            st.session_state['question_types_config'] = {}
            st.session_state['selected_question_types'] = []
            st.session_state['question_type_selector'] = []
            
            # Clear file uploader keys
            keys_to_del = [
                'universal_pdf',
                'universal_new_concept_pdf',
                'universal_paste_btn',
                'universal_source'
            ]
            
            # Add dynamic keys
            for k in list(st.session_state.keys()):
                if (k.startswith('general_') or 
                    k.startswith('count_') or 
                    k.startswith('mcq_') or 
                    k.startswith('fib_') or 
                    k.startswith('ar_') or 
                    k.startswith('cs_') or 
                    k.startswith('mp_') or 
                    k.startswith('desc_')):
                    keys_to_del.append(k)
            
            for k in keys_to_del:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()
            
    with col_clr_out:
        if st.button("Clear Outputs", help="Clear all generated results"):
            st.session_state.generated_output = None
            st.rerun()

# Main content area
tab1, tab2 = st.tabs(["📝 Configure & Generate", "📄 Results"])

with tab1:
    st.markdown('<div class="section-header">General Information</div>', unsafe_allow_html=True)
    
    # Curriculum and Subject are hardcoded
    curriculum = "NCERT"
    subject = "Science"
    
    grade = st.selectbox(
        "Grade",
        [f"Grade {i}" for i in range(3, 9)],
        help="Select the grade level",
        key="general_grade"
    )
    
    chapter = st.text_input(
        "Chapter/Unit Name",
        placeholder="e.g., Photosynthesis",
        help="Enter the chapter or unit name",
        key="general_chapter"
    )

    science_domain = st.selectbox(
        "Science Domain Reference (MANDATORY)",
        ["Life Science", "Physical Science", "Earth Science", "Environmental Science"],
        help="Select the specific science domain for these questions",
        key="general_science_domain"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        old_concept = st.text_area(
            "Old Concepts (Prerequisites)",
            placeholder="Enter prerequisite knowledge the student already has...",
            height=150,
            help="Concepts students should already know",
            key="general_old_concept"
        )
    
    with col2:
        new_concept = st.text_area(
            "New Concepts (Current Chapter)",
            placeholder="Enter the concepts being taught in this chapter...",
            height=150,
            help="New concepts being taught",
            key="general_new_concept"
        )
    
    # Universal file upload option (PDF or Image)
    st.markdown("### 📄 Universal New Concept File (Optional)")
    st.info("💡 Upload a PDF or image that will be used for ALL questions that select 'New Concept File' as their source. This is a universal file that applies across all question types.")
    
    col_upload, col_paste = st.columns([3, 1])
    
    # Callback for uploader
    def on_uploader_change():
        if st.session_state.universal_new_concept_pdf:
            st.session_state.universal_pdf = st.session_state.universal_new_concept_pdf
            st.session_state.universal_source = 'upload'
            # Clear paste if upload happens
            # But we can't clear paste button visual state easily, but we update our source of truth.
        else:
            # Explicitly cleared via X
            st.session_state.universal_pdf = None
            st.session_state.universal_source = None

    with col_upload:
        universal_pdf_upload = st.file_uploader(
            "Upload Universal New Concept File (PDF/Image)",
            type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
            key="universal_new_concept_pdf",
            help="This file will be used for all questions that select 'pdf' as their new concept source",
            on_change=on_uploader_change
        )

    with col_paste:
        st.markdown("<br>", unsafe_allow_html=True)  # Align with uploader
        pasted_content = paste(label="📋 Paste Image", key="universal_paste_btn")
    
    # Initialize source if needed
    if 'universal_source' not in st.session_state:
        st.session_state.universal_source = None

    # Logic to handle paste (upload handled by callback)
    if pasted_content:
        # Convert pasted bytes to file-like object
        st.session_state.universal_pdf = PastedFile(pasted_content, name="pasted_universal_image.png")
        st.session_state.universal_source = 'paste'
    
    # Also sync immediately if uploader has a file (callback runs on next rerun)
    # This ensures the session state is updated in the same script run
    if universal_pdf_upload and not st.session_state.get('universal_pdf'):
        st.session_state.universal_pdf = universal_pdf_upload
        st.session_state.universal_source = 'upload'
    
    # Check if we have a valid file now
    universal_pdf = st.session_state.get('universal_pdf')

    # Store/Update session state (redundant but safe)
    if universal_pdf:
        st.success(f"✅ Universal file ready: {universal_pdf.name}")
    else:
        # Ensure consistent state
        st.session_state.universal_pdf = None
    
    additional_notes = st.text_area(
        "Additional Notes (Optional)",
        placeholder="Any special instructions for question generation...",
        height=100,
        help="Extra instructions or configuration",
        key="general_additional_notes"
    )
    
    st.markdown("---")
    
    st.markdown('<div class="section-header">Question Types Configuration</div>', unsafe_allow_html=True)
    
    # Question type selection
    question_types = [
        "MCQ",
        "Fill in the Blanks",
        "Descriptive",
        # "Case Study",
        # "Multi-Part",
        # "Assertion-Reasoning",
        # "Descriptive w/ Subquestions"
    ]
    
    taxonomy_options = [
        "Remembering",
        "Understanding",
        "Applying",
        "Evaluating",
        "Analysing"
    ]
    
    # Initialize selected_types in session state if not exists
    if 'selected_question_types' not in st.session_state:
        st.session_state.selected_question_types = []
    
    # Add question type selector
    st.markdown("### Select Question Types to Configure")
    
    selected_types = st.multiselect(
        "Choose question types",
        question_types,
        default=st.session_state.selected_question_types,
        key="question_type_selector"
    )
    
    # Update session state with current selection
    st.session_state.selected_question_types = selected_types
    
    # Remove deselected types
    for qtype in list(st.session_state.question_types_config.keys()):
        if qtype not in selected_types:
            del st.session_state.question_types_config[qtype]
    
    # Configure each selected type
    for qtype in selected_types:
        if qtype not in st.session_state.question_types_config:
            # Initialize with 1 default question with empty values
            default_questions = []
            default_questions.append({
                'topic': '',
                'new_concept_source': 'pdf',  # Default to pdf
                'new_concept_pdf': None,
                'additional_notes_source': 'none',  # Default to none
                'additional_notes_text': '',  # Per-question additional notes text
                'additional_notes_pdf': None,
                'dok': 1,
                'marks': 1.0,
                'taxonomy': 'Remembering'
            })
            
            st.session_state.question_types_config[qtype] = {
                'count': 1, 
                'questions': default_questions
            }
        
        with st.expander(f"⚙️ {qtype} Configuration", expanded=True):
            # Number of questions for this type
            # Set max_value based on question type
            if qtype == "MCQ":
                max_questions = 34
            elif qtype in ["Fill in the Blanks", "Multi-Part"]:
                max_questions = 32
            else:
                max_questions = 20
            
            # Create columns for number input, max button, and clear button
            col_input, col_max, col_clear = st.columns([3, 1, 1])
            
            # Initialize widget key if Max button was clicked
            widget_key = f"count_{qtype}"
            if widget_key not in st.session_state:
                st.session_state[widget_key] = st.session_state.question_types_config[qtype].get('count', 1)
            
            with col_max:
                # Add some spacing to align with the input
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("📊 Max", key=f"max_btn_{qtype}", help=f"Set to maximum ({max_questions})"):
                    st.session_state[widget_key] = max_questions
                    st.session_state.question_types_config[qtype]['count'] = max_questions
                    st.rerun()

            with col_clear:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"clear_btn_{qtype}", help=f"Reset {qtype} configuration"):
                    # Reset specific config
                    if qtype in st.session_state.question_types_config:
                        # Reset to default single question
                        st.session_state.question_types_config[qtype] = {
                            'count': 1, 
                            'questions': [{
                                'topic': '',
                                'new_concept_source': 'pdf',
                                'new_concept_pdf': None,
                                'additional_notes_source': 'none',
                                'additional_notes_text': '',
                                'additional_notes_pdf': None,
                                'dok': 1,
                                'marks': 1.0,
                                'taxonomy': 'Remembering'
                            }]
                        }
                        # Update the number input widget
                        st.session_state[widget_key] = 1
                        st.rerun()
            
            with col_input:
                num_questions = st.number_input(
                    f"Number of {qtype} Questions",
                    min_value=1,
                    max_value=max_questions,
                    key=widget_key
                )
            
            st.session_state.question_types_config[qtype]['count'] = num_questions
            
            # Initialize questions list if needed
            current_count = len(st.session_state.question_types_config[qtype].get('questions', []))
            if num_questions != current_count:
                if num_questions > current_count:
                    # Add new questions
                    for i in range(current_count, num_questions):
                        st.session_state.question_types_config[qtype]['questions'].append({
                            'topic': '',
                            'new_concept_source': 'pdf',  # Default to pdf
                            'new_concept_pdf': None,
                            'additional_notes_source': 'none',  # Default to none
                            'additional_notes_text': '',  # Per-question additional notes text
                            'additional_notes_pdf': None
                        })
                else:
                    # Remove excess
                    st.session_state.question_types_config[qtype]['questions'] = \
                        st.session_state.question_types_config[qtype]['questions'][:num_questions]
            
            # Type-specific configuration
            if qtype == "MCQ":
                st.markdown("#### MCQ Questions Configuration")
                for i in range(num_questions):
                    st.markdown(f"**Question {i+1}**")
                    cols = st.columns([3, 3, 1, 1, 2])
                    
                    with cols[0]:
                        topic = st.text_input(
                            "Topic",
                            key=f"mcq_topic_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                            placeholder="e.g., Solar System"
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic
                    
                    with cols[1]:
                        mcq_type_options = [
                            "Auto",
                            "Number Based",
                            "Image Based", 
                            "Text (Content) Based",
                            "Statement Based MCQ",
                            "Assertion–Reason",
                            "Image and Statement Based",
                            "Real Life Based",
                            "Data Based",
                            "Real Life Image Based",
                            "Equation Based",
                            "Graph Based"
                        ]
                        current_type = st.session_state.question_types_config[qtype]['questions'][i].get('mcq_type', 'Auto')
                        mcq_type = st.selectbox(
                            "MCQ Type",
                            mcq_type_options,
                            key=f"mcq_type_{i}",
                            index=mcq_type_options.index(current_type) if current_type in mcq_type_options else 0
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['mcq_type'] = mcq_type

                    with cols[2]:
                        dok = st.selectbox(
                            "DOK",
                            [1, 2, 3],
                            key=f"mcq_dok_{i}",
                            index=st.session_state.question_types_config[qtype]['questions'][i].get('dok', 1) - 1
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['dok'] = dok
                    
                    with cols[3]:
                        marks = st.number_input(
                            "Marks",
                            min_value=0.5,
                            max_value=10.0,
                            step=0.5,
                            key=f"mcq_marks_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('marks', 1.0)
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['marks'] = marks
                    
                    with cols[4]:
                        taxonomy = st.selectbox(
                            "Taxonomy",
                            taxonomy_options,
                            key=f"mcq_taxonomy_{i}",
                            index=taxonomy_options.index(
                                st.session_state.question_types_config[qtype]['questions'][i].get('taxonomy', 'Remembering')
                            )
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['taxonomy'] = taxonomy
                    
                    # New Concept Source Selection (MANDATORY)
                    st.markdown("**New Concept Source:**")
                    new_concept_source = st.radio(
                        "Select new concept source",
                        options=["text", "pdf"],
                        format_func=lambda x: {
                            "text": "📝 Use Universal Text Concept",
                            "pdf": "📄 Use Universal File (PDF/Image)"
                        }[x],
                        key=f"mcq_new_concept_source_{i}",
                        index=["text", "pdf"].index(
                            st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                        ),
                        horizontal=True
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source
                    
                    # Show info message based on selection
                    if new_concept_source == 'pdf':
                        if st.session_state.get('universal_pdf'):
                            st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                        else:
                            st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    
                    # Additional Notes Selection (OPTIONAL)
                    st.markdown("**Additional Notes (Optional):**")
                    col_cb1, col_cb2 = st.columns(2)
                    with col_cb1:
                        has_text_note = st.checkbox("Add Text Note", key=f"mcq_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                    with col_cb2:
                        has_file_note = st.checkbox("Add File", key=f"mcq_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))
                    
                    # Handle Text Note
                    if has_text_note:
                        additional_notes_text = st.text_area(
                            "Additional Notes Text",
                            key=f"mcq_additional_notes_text_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                            placeholder="Enter specific notes/instructions for this question...",
                            height=100
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''
                        
                    # Handle File Note
                    if has_file_note:
                        col_u, col_p = st.columns([3, 1])
                        with col_u:
                            an_upload = st.file_uploader(
                                "Upload Additional Notes File (PDF/Image)",
                                type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                key=f"mcq_additional_notes_pdf_{i}"
                            )
                        with col_p:
                            st.markdown("<br>", unsafe_allow_html=True)
                            an_paste = paste(label="📋 Paste", key=f"mcq_paste_{i}")
                        
                        an_final = None
                        if an_upload:
                            an_final = an_upload
                        elif an_paste:
                            an_final = PastedFile(an_paste, name=f"pasted_mcq_{i}.png")
                            
                        # Only update if a new file is provided or keep existing if not explicitly cleared? 
                        # Streamlit file uploader handles persistence usually within the run, but here we are manually mapping.
                        # We should trust the uploader's state for 'an_upload'.
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                        
                        if an_final:
                            st.success(f"✅ Ready: {an_final.name}")
                    else:
                         st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None
                    
                    # Update source for compatibility
                    if has_text_note and has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                    elif has_text_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                    elif has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'
                    
                    st.markdown("---")
            
            elif qtype == "Assertion-Reasoning":
                st.markdown("#### Assertion-Reasoning Configuration")
                st.info("ℹ️ Assertion-Reasoning questions have predefined configuration in the prompt. Only specify topics.")
                
                for i in range(num_questions):
                    topic = st.text_input(
                        f"Question {i+1} Topic",
                        key=f"ar_topic_{i}",
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                        placeholder="e.g., Photosynthesis Process"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic
                    
                    # New Concept Source Selection (MANDATORY)
                    st.markdown("**New Concept Source:**")
                    new_concept_source = st.radio(
                        "Select new concept source",
                        options=["text", "pdf"],
                        format_func=lambda x: {
                            "text": "📝 Use Universal Text Concept",
                            "pdf": "📄 Use Universal File (PDF/Image)"
                        }[x],
                        key=f"ar_new_concept_source_{i}",
                        index=["text", "pdf"].index(
                            st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                        ),
                        horizontal=True
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source
                    
                    if new_concept_source == 'pdf':
                        if st.session_state.get('universal_pdf'):
                            st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                        else:
                            st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    
                    # Additional Notes Selection (OPTIONAL)
                    st.markdown("**Additional Notes (Optional):**")
                    col_cb1, col_cb2 = st.columns(2)
                    with col_cb1:
                        has_text_note = st.checkbox("Add Text Note", key=f"ar_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                    with col_cb2:
                        has_file_note = st.checkbox("Add File", key=f"ar_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))

                    # Handle Text Note
                    if has_text_note:
                        additional_notes_text = st.text_area(
                            "Additional Notes Text",
                            key=f"ar_additional_notes_text_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                            placeholder="Enter specific notes/instructions for this question...",
                            height=100
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''

                    # Handle File Note
                    if has_file_note:
                        col_u, col_p = st.columns([3, 1])
                        with col_u:
                            an_upload = st.file_uploader(
                                "Upload Additional Notes File (PDF/Image)",
                                type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                key=f"ar_additional_notes_pdf_{i}"
                            )
                        with col_p:
                            st.markdown("<br>", unsafe_allow_html=True)
                            an_paste = paste(label="📋 Paste", key=f"ar_paste_{i}")
                            
                        an_final = None
                        if an_upload:
                            an_final = an_upload
                        elif an_paste:
                            an_final = PastedFile(an_paste, name=f"pasted_ar_{i}.png")

                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                        if an_final:
                            st.success(f"✅ Ready: {an_final.name}")
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None

                    # Update source for compatibility
                    if has_text_note and has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                    elif has_text_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                    elif has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'
                    
                    st.markdown("---")
            
            elif qtype == "Fill in the Blanks":
                st.markdown("#### Fill in the Blanks Configuration")
                
                # Per-question config with subparts
                for i in range(num_questions):
                    st.markdown(f"**Question {i+1}**")
                    
                    # Topic field
                    topic = st.text_input(
                        "Topic",
                        key=f"fib_topic_{i}",
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                        placeholder="e.g., Parts of a Plant"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic
                    
                    # Number of subparts for this specific question
                    num_subparts = st.number_input(
                        "Number of Sub-Parts",
                        min_value=1,
                        max_value=5,
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('num_subparts', 1),
                        key=f"fib_subparts_{i}",
                        help="Set to 1 for single-part, or 2-5 for questions with roman numeral subparts (i, ii, iii, etc.)"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['num_subparts'] = num_subparts
                    
                    # FIB Type Selection
                    fib_type_options = [
                        "Auto",
                        "Concept (definition)",
                        "Scenario-Based FIB",
                        "REAL LIFE IMAGES BASED",
                        "IMAGE BASED",
                        "Image-Based Science Observation",
                        "Data Based",
                        "Numerical and Image Based",
                        "Equation Based",
                        "Graph Based"
                    ]
                    current_fib_type = st.session_state.question_types_config[qtype]['questions'][i].get('fib_type', 'Auto')
                    fib_type = st.selectbox(
                        "FIB Type",
                        fib_type_options,
                        key=f"fib_type_{i}",
                        index=fib_type_options.index(current_fib_type) if current_fib_type in fib_type_options else 0
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['fib_type'] = fib_type
                    
                    # If single-part (num_subparts = 1), show DOK, Marks, Taxonomy directly
                    if num_subparts == 1:
                        # Clear any stale subparts_config from a previous multi-part selection
                        st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = []
                        cols = st.columns([1, 1, 2])
                        
                        with cols[0]:
                            dok = st.selectbox(
                                "DOK",
                                [1, 2, 3],
                                key=f"fib_dok_{i}",
                                index=st.session_state.question_types_config[qtype]['questions'][i].get('dok', 1) - 1
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['dok'] = dok
                        
                        with cols[1]:
                            marks = st.number_input(
                                "Marks",
                                min_value=0.5,
                                max_value=10.0,
                                step=0.5,
                                key=f"fib_marks_{i}",
                                value=st.session_state.question_types_config[qtype]['questions'][i].get('marks', 1.0)
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['marks'] = marks
                        
                        with cols[2]:
                            taxonomy = st.selectbox(
                                "Taxonomy",
                                taxonomy_options,
                                key=f"fib_taxonomy_{i}",
                                index=taxonomy_options.index(
                                    st.session_state.question_types_config[qtype]['questions'][i].get('taxonomy', 'Remembering')
                                )
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['taxonomy'] = taxonomy
                    
                    else:
                        # Multi-part: show subpart configuration
                        # Initialize subparts for this question
                        if 'subparts_config' not in st.session_state.question_types_config[qtype]['questions'][i]:
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = []
                        
                        current_subparts = len(st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'])
                        if num_subparts != current_subparts:
                            if num_subparts > current_subparts:
                                for j in range(current_subparts, num_subparts):
                                    roman_numerals = ['i', 'ii', 'iii', 'iv', 'v']
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'].append({
                                        'part': roman_numerals[j] if j < len(roman_numerals) else f'part_{j+1}',
                                        'dok': 1,
                                        'marks': 1.0,
                                        'taxonomy': 'Remembering'
                                    })
                            else:
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = \
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][:num_subparts]
                        
                        # Subparts config
                        st.markdown("**Sub-Parts Configuration**")
                        for j in range(num_subparts):
                            cols = st.columns([1, 1, 1, 2])
                            roman_numerals = ['i', 'ii', 'iii', 'iv', 'v']
                            
                            with cols[0]:
                                st.markdown(f"Part ({roman_numerals[j] if j < len(roman_numerals) else j+1})")
                            
                            with cols[1]:
                                dok = st.selectbox(
                                    "DOK",
                                    [1, 2, 3],
                                    key=f"fib_subpart_dok_{i}_{j}",
                                    index=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('dok', 1) - 1
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['dok'] = dok
                            
                            with cols[2]:
                                marks = st.number_input(
                                    "Marks",
                                    min_value=0.5,
                                    max_value=10.0,
                                    step=0.5,
                                    key=f"fib_subpart_marks_{i}_{j}",
                                    value=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('marks', 1.0)
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['marks'] = marks
                            
                            with cols[3]:
                                taxonomy = st.selectbox(
                                    "Taxonomy",
                                    taxonomy_options,
                                    key=f"fib_subpart_taxonomy_{i}_{j}",
                                    index=taxonomy_options.index(
                                        st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('taxonomy', 'Remembering')
                                    )
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['taxonomy'] = taxonomy
                    
                    # --- Aggregate subpart values to top-level for pipeline compatibility ---
                    subparts_cfg = st.session_state.question_types_config[qtype]['questions'][i].get('subparts_config', [])
                    if subparts_cfg:
                        st.session_state.question_types_config[qtype]['questions'][i]['dok'] = subparts_cfg[0].get('dok', 1)
                        st.session_state.question_types_config[qtype]['questions'][i]['marks'] = sum(s.get('marks', 1.0) for s in subparts_cfg)
                        st.session_state.question_types_config[qtype]['questions'][i]['taxonomy'] = subparts_cfg[0].get('taxonomy', 'Remembering')
                    
                    # New Concept Source Selection (MANDATORY)
                    st.markdown("**New Concept Source:**")
                    new_concept_source = st.radio(
                        "Select new concept source",
                        options=["text", "pdf"],
                        format_func=lambda x: {
                            "text": "📝 Use Universal Text Concept",
                            "pdf": "📄 Use Universal File (PDF/Image)"
                        }[x],
                        key=f"fib_new_concept_source_{i}",
                        index=["text", "pdf"].index(
                            st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                        ),
                        horizontal=True
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source
                    
                    if new_concept_source == 'pdf':
                        if st.session_state.get('universal_pdf'):
                            st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                        else:
                            st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    
                    # Additional Notes Selection (OPTIONAL)
                    st.markdown("**Additional Notes (Optional):**")
                    col_cb1, col_cb2 = st.columns(2)
                    with col_cb1:
                        has_text_note = st.checkbox("Add Text Note", key=f"fib_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                    with col_cb2:
                        has_file_note = st.checkbox("Add File", key=f"fib_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))

                    # Handle Text Note
                    if has_text_note:
                        additional_notes_text = st.text_area(
                            "Additional Notes Text",
                            key=f"fib_additional_notes_text_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                            placeholder="Enter specific notes/instructions for this question...",
                            height=100
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''

                    # Handle File Note
                    if has_file_note:
                        col_u, col_p = st.columns([3, 1])
                        with col_u:
                            an_upload = st.file_uploader(
                                "Upload Additional Notes File (PDF/Image)",
                                type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                key=f"fib_additional_notes_pdf_{i}"
                            )
                        with col_p:
                            st.markdown("<br>", unsafe_allow_html=True)
                            an_paste = paste(label="📋 Paste", key=f"fib_paste_{i}")
                            
                        an_final = None
                        if an_upload:
                            an_final = an_upload
                        elif an_paste:
                            an_final = PastedFile(an_paste, name=f"pasted_fib_{i}.png")

                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                        if an_final:
                            st.success(f"✅ Ready: {an_final.name}")
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None
                        
                    # Update source for compatibility
                    if has_text_note and has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                    elif has_text_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                    elif has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'
                    
                    st.markdown("---")
            
            elif qtype in ["Descriptive", "Descriptive w/ Subquestions"]:
                st.markdown(f"#### {qtype} Configuration")

                for i in range(num_questions):
                    st.markdown(f"**Question {i+1}**")

                    # Topic field
                    topic = st.text_input(
                        "Topic",
                        key=f"{qtype}_topic_{i}",
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                        placeholder="e.g., nth term of AP"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic

                    # Number of sub-parts
                    num_subparts = st.number_input(
                        "Number of Sub-Parts",
                        min_value=1,
                        max_value=5,
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('num_subparts', 1),
                        key=f"{qtype}_subparts_{i}",
                        help="Set to 1 for a single question, or 2–5 for questions with roman numeral sub-parts (i, ii, iii, …)"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['num_subparts'] = num_subparts

                    # Add Without Stem option
                    without_stem = st.checkbox(
                        "Descriptive without stem",
                        key=f"{qtype}_without_stem_{i}",
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('without_stem', False),
                        help="Check this box to avoid having a detailed stem/scenario."
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['without_stem'] = without_stem

                    # Descriptive Type selectbox
                    descriptive_type_options = [
                        "Auto",
                        "Concept (definition)",
                        "Scenario-Based",
                        "REAL LIFE IMAGES BASED",
                        "IMAGE BASED",
                        "Image-Based Science Observation",
                        "Data Based",
                        "Numerical and Image Based",
                        "Equation Based",
                        "Graph Based"
                    ]
                    
                    if without_stem:
                        descriptive_type_options.remove("Auto")
                        
                    current_desc_type = st.session_state.question_types_config[qtype]['questions'][i].get('descriptive_type', 'Auto')
                    
                    # fallback if current choice is no longer in the list
                    if current_desc_type not in descriptive_type_options:
                        current_desc_type = descriptive_type_options[0]
                        
                    descriptive_type = st.selectbox(
                        "Descriptive Type",
                        descriptive_type_options,
                        key=f"{qtype}_desc_type_{i}",
                        index=descriptive_type_options.index(current_desc_type)
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['descriptive_type'] = descriptive_type

                    # Single-part layout
                    if num_subparts == 1:
                        # Clear any stale subparts_config
                        st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = []
                        cols = st.columns([1, 1, 2])

                        with cols[0]:
                            dok = st.selectbox(
                                "DOK",
                                [1, 2, 3],
                                key=f"{qtype}_dok_{i}",
                                index=st.session_state.question_types_config[qtype]['questions'][i].get('dok', 1) - 1
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['dok'] = dok

                        with cols[1]:
                            marks = st.number_input(
                                "Marks",
                                min_value=0.5,
                                max_value=10.0,
                                step=0.5,
                                key=f"{qtype}_marks_{i}",
                                value=st.session_state.question_types_config[qtype]['questions'][i].get('marks', 1.0)
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['marks'] = marks

                        with cols[2]:
                            taxonomy = st.selectbox(
                                "Taxonomy",
                                taxonomy_options,
                                key=f"{qtype}_taxonomy_{i}",
                                index=taxonomy_options.index(
                                    st.session_state.question_types_config[qtype]['questions'][i].get('taxonomy', 'Remembering')
                                )
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['taxonomy'] = taxonomy

                    else:
                        # Multi-part: show per-subpart config
                        if 'subparts_config' not in st.session_state.question_types_config[qtype]['questions'][i]:
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = []

                        current_subparts = len(st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'])
                        if num_subparts != current_subparts:
                            if num_subparts > current_subparts:
                                for j in range(current_subparts, num_subparts):
                                    roman_numerals = ['i', 'ii', 'iii', 'iv', 'v']
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'].append({
                                        'part': roman_numerals[j] if j < len(roman_numerals) else f'part_{j+1}',
                                        'dok': 1,
                                        'marks': 1.0,
                                        'taxonomy': 'Remembering'
                                    })
                            else:
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = \
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][:num_subparts]

                        st.markdown("**Sub-Parts Configuration**")
                        for j in range(num_subparts):
                            cols = st.columns([1, 1, 1, 2])
                            roman_numerals = ['i', 'ii', 'iii', 'iv', 'v']

                            with cols[0]:
                                st.markdown(f"Part ({roman_numerals[j] if j < len(roman_numerals) else j+1})")

                            with cols[1]:
                                dok = st.selectbox(
                                    "DOK",
                                    [1, 2, 3],
                                    key=f"{qtype}_subpart_dok_{i}_{j}",
                                    index=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('dok', 1) - 1
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['dok'] = dok

                            with cols[2]:
                                marks = st.number_input(
                                    "Marks",
                                    min_value=0.5,
                                    max_value=10.0,
                                    step=0.5,
                                    key=f"{qtype}_subpart_marks_{i}_{j}",
                                    value=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('marks', 1.0)
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['marks'] = marks

                            with cols[3]:
                                taxonomy = st.selectbox(
                                    "Taxonomy",
                                    taxonomy_options,
                                    key=f"{qtype}_subpart_taxonomy_{i}_{j}",
                                    index=taxonomy_options.index(
                                        st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('taxonomy', 'Remembering')
                                    )
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['taxonomy'] = taxonomy

                        # Aggregate subpart values to top-level for pipeline compatibility
                        subparts_cfg = st.session_state.question_types_config[qtype]['questions'][i].get('subparts_config', [])
                        if subparts_cfg:
                            st.session_state.question_types_config[qtype]['questions'][i]['dok'] = subparts_cfg[0].get('dok', 1)
                            st.session_state.question_types_config[qtype]['questions'][i]['marks'] = sum(s.get('marks', 1.0) for s in subparts_cfg)
                            st.session_state.question_types_config[qtype]['questions'][i]['taxonomy'] = subparts_cfg[0].get('taxonomy', 'Remembering')

                    # New Concept Source Selection (MANDATORY)
                    st.markdown("**New Concept Source:**")
                    new_concept_source = st.radio(
                        "Select new concept source",
                        options=["text", "pdf"],
                        format_func=lambda x: {
                            "text": "📝 Use Universal Text Concept",
                            "pdf": "📄 Use Universal File (PDF/Image)"
                        }[x],
                        key=f"{qtype}_new_concept_source_{i}",
                        index=["text", "pdf"].index(
                            st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                        ),
                        horizontal=True
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source

                    if new_concept_source == 'pdf':
                        if st.session_state.get('universal_pdf'):
                            st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                        else:
                            st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None

                    # Additional Notes Selection (OPTIONAL)
                    st.markdown("**Additional Notes (Optional):**")
                    col_cb1, col_cb2 = st.columns(2)
                    with col_cb1:
                        has_text_note = st.checkbox("Add Text Note", key=f"{qtype}_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                    with col_cb2:
                        has_file_note = st.checkbox("Add File", key=f"{qtype}_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))

                    # Handle Text Note
                    if has_text_note:
                        additional_notes_text = st.text_area(
                            "Additional Notes Text",
                            key=f"{qtype}_additional_notes_text_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                            placeholder="Enter specific notes/instructions for this question...",
                            height=100
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''

                    # Handle File Note
                    if has_file_note:
                        col_u, col_p = st.columns([3, 1])
                        with col_u:
                            an_upload = st.file_uploader(
                                "Upload Additional Notes File (PDF/Image)",
                                type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                key=f"{qtype}_additional_notes_pdf_{i}"
                            )
                        with col_p:
                            st.markdown("<br>", unsafe_allow_html=True)
                            an_paste = paste(label="📋 Paste", key=f"{qtype}_paste_{i}")

                        an_final = None
                        if an_upload:
                            an_final = an_upload
                        elif an_paste:
                            an_final = PastedFile(an_paste, name=f"pasted_{qtype}_{i}.png")

                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                        if an_final:
                            st.success(f"✅ Ready: {an_final.name}")
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None

                    # Update source for compatibility
                    if has_text_note and has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                    elif has_text_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                    elif has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'

                    st.markdown("---")
            
            elif qtype == "Case Study":
                st.markdown("#### Case Study Configuration")
                
                for i in range(num_questions):
                    st.markdown(f"**Case Study {i+1}**")
                    
                    topic = st.text_input(
                        "Topic",
                        key=f"case_topic_{i}",
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                        placeholder="e.g., Applications of AP"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic
                    
                    # New Concept Source Selection (MANDATORY)
                    st.markdown("**New Concept Source:**")
                    new_concept_source = st.radio(
                        "Select new concept source",
                        options=["text", "pdf"],
                        format_func=lambda x: {
                            "text": "📝 Use Universal Text Concept",
                            "pdf": "📄 Use Universal File (PDF/Image)"
                        }[x],
                        key=f"case_new_concept_source_{i}",
                        index=["text", "pdf"].index(
                            st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                        ),
                        horizontal=True
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source
                    
                    if new_concept_source == 'pdf':
                        if st.session_state.get('universal_pdf'):
                            st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                        else:
                            st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_pdf'] = None
                    
                    # Additional Notes Selection (OPTIONAL)
                    st.markdown("**Additional Notes (Optional):**")
                    col_cb1, col_cb2 = st.columns(2)
                    with col_cb1:
                        has_text_note = st.checkbox("Add Text Note", key=f"case_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                    with col_cb2:
                        has_file_note = st.checkbox("Add File", key=f"case_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))

                    # Handle Text Note
                    if has_text_note:
                        additional_notes_text = st.text_area(
                            "Additional Notes Text",
                            key=f"case_additional_notes_text_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                            placeholder="Enter specific notes/instructions for this question...",
                            height=100
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''

                    # Handle File Note
                    if has_file_note:
                        # Use file uploader directly as per original Case Study block (which seemed to miss the paste button in the original code, but I'll add checking the original code again... wait, Case Study specific block in original code didn't have paste button in the reading? Let me check line 1017. It says `additional_notes_pdf = st.file_uploader(...)`. It didn't have paste. I should probably ADD paste for consistency, or keep it simple. I'll stick to original functionality + checkboxes, but wait, the plan implies consistency. I will add paste for consistency as it's better.)
                        # Actually, looking at the previous blocks, paste was added. I'll add paste here too to be consistent with others.
                        col_u, col_p = st.columns([3, 1])
                        with col_u:
                             an_upload = st.file_uploader(
                                "Upload Additional Notes File (PDF/Image)",
                                type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                key=f"case_additional_notes_pdf_{i}"
                            )
                        with col_p:
                            st.markdown("<br>", unsafe_allow_html=True)
                            an_paste = paste(label="📋 Paste", key=f"case_paste_{i}")
                        
                        an_final = None
                        if an_upload:
                            an_final = an_upload
                        elif an_paste:
                            an_final = PastedFile(an_paste, name=f"pasted_case_{i}.png")
                            
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                        if an_final:
                            st.success(f"✅ Ready: {an_final.name}")
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None

                    # Update source for compatibility
                    if has_text_note and has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                    elif has_text_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                    elif has_file_note:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                    else:
                        st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'
                    
                    # Number of subparts
                    num_subparts = st.number_input(
                        "Number of Sub-Parts",
                        min_value=2,
                        max_value=5,
                        value=st.session_state.question_types_config[qtype]['questions'][i].get('num_subparts', 3),
                        key=f"case_subparts_{i}"
                    )
                    st.session_state.question_types_config[qtype]['questions'][i]['num_subparts'] = num_subparts
                    
                    # Initialize subparts
                    if 'subparts' not in st.session_state.question_types_config[qtype]['questions'][i]:
                        st.session_state.question_types_config[qtype]['questions'][i]['subparts'] = []
                    
                    current_subparts = len(st.session_state.question_types_config[qtype]['questions'][i]['subparts'])
                    if num_subparts != current_subparts:
                        if num_subparts > current_subparts:
                            for j in range(current_subparts, num_subparts):
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts'].append({
                                    'part': chr(97 + j),
                                    'dok': 1,
                                    'marks': 1.0
                                })
                        else:
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts'] = \
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts'][:num_subparts]
                    
                    # Subparts config (NO Taxonomy for Case Study)
                    st.markdown("**Sub-Parts Configuration** (No Taxonomy needed)")
                    for j in range(num_subparts):
                        cols = st.columns([1, 1, 1])
                        
                        with cols[0]:
                            st.markdown(f"Part ({chr(97 + j)})")
                        
                        with cols[1]:
                            dok = st.selectbox(
                                "DOK",
                                [1, 2, 3],
                                key=f"case_subpart_dok_{i}_{j}",
                                index=st.session_state.question_types_config[qtype]['questions'][i]['subparts'][j].get('dok', 1) - 1
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts'][j]['dok'] = dok
                        
                        with cols[2]:
                            marks = st.number_input(
                                "Marks",
                                min_value=0.5,
                                max_value=10.0,
                                step=0.5,
                                key=f"case_subpart_marks_{i}_{j}",
                                value=st.session_state.question_types_config[qtype]['questions'][i]['subparts'][j].get('marks', 1.0)
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts'][j]['marks'] = marks
                    
                    st.markdown("---")
            
            elif qtype == "Multi-Part":
                st.markdown("#### Multi-Part Configuration")
                st.info("Configure each Multi-Part question individually. You can define specific sub-parts for each question.")
                
                # Per-question config
                for i in range(num_questions):
                    with st.expander(f"Question {i+1} Configuration", expanded=True):
                        
                        # Add Topic field
                        topic = st.text_input(
                            "Topic",
                            key=f"multipart_topic_{i}",
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('topic', ''),
                            placeholder="e.g., nth term of AP"
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['topic'] = topic
                        
                        # New Concept Source Selection
                        st.markdown("**New Concept Source:**")
                        new_concept_source = st.radio(
                            "Select new concept source",
                            options=["text", "pdf"],
                            format_func=lambda x: {
                                "text": "📝 Use Universal Text Concept",
                                "pdf": "📄 Use Universal File (PDF/Image)"
                            }[x],
                            key=f"multipart_new_concept_source_{i}",
                            index=["text", "pdf"].index(
                                st.session_state.question_types_config[qtype]['questions'][i].get('new_concept_source', 'pdf')
                            ),
                            horizontal=True
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['new_concept_source'] = new_concept_source
                        
                        if new_concept_source == 'pdf':
                            if st.session_state.get('universal_pdf'):
                                st.info(f"ℹ️ Will use universal file: **{st.session_state.universal_pdf.name}**")
                            else:
                                st.warning("⚠️ Please upload a Universal File (PDF/Image) in the General Information section above")
                        
                        # Additional Notes Selection (OPTIONAL)
                        st.markdown("**Additional Notes (Optional):**")
                        col_cb1, col_cb2 = st.columns(2)
                        with col_cb1:
                            has_text_note = st.checkbox("Add Text Note", key=f"multipart_cb_text_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', '')))
                        with col_cb2:
                            has_file_note = st.checkbox("Add File", key=f"multipart_cb_file_{i}", value=bool(st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_pdf', None)))

                        # Handle Text Note
                        if has_text_note:
                            additional_notes_text = st.text_area(
                                "Additional Notes Text",
                                key=f"multipart_additional_notes_text_{i}",
                                value=st.session_state.question_types_config[qtype]['questions'][i].get('additional_notes_text', ''),
                                placeholder="Enter specific notes/instructions for this question...",
                                height=100
                            )
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = additional_notes_text
                        else:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_text'] = ''

                        # Handle File Note
                        if has_file_note:
                            col_u, col_p = st.columns([3, 1])
                            with col_u:
                                an_upload = st.file_uploader(
                                    "Upload Additional Notes File (PDF/Image)",
                                    type=['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
                                    key=f"multipart_additional_notes_pdf_{i}"
                                )
                            with col_p:
                                st.markdown("<br>", unsafe_allow_html=True)
                                an_paste = paste(label="📋 Paste", key=f"multipart_paste_{i}")
                            
                            an_final = None
                            if an_upload:
                                an_final = an_upload
                            elif an_paste:
                                an_final = PastedFile(an_paste, name=f"pasted_multipart_{i}.png")
                                
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = an_final
                            if an_final:
                                st.success(f"✅ Ready: {an_final.name}")
                        else:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_pdf'] = None

                        # Update source for compatibility
                        if has_text_note and has_file_note:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'both'
                        elif has_text_note:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'text'
                        elif has_file_note:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'pdf'
                        else:
                            st.session_state.question_types_config[qtype]['questions'][i]['additional_notes_source'] = 'none'
                        
                        st.markdown("---")
                        
                        # Sub-Part Configuration (Per Question)
                        st.markdown("**Sub-Parts Configuration**")
                        
                        num_subparts = st.number_input(
                            "Number of Sub-Parts",
                            min_value=2,
                            max_value=5,
                            value=st.session_state.question_types_config[qtype]['questions'][i].get('num_subparts', 2),
                            key=f"multipart_subparts_{i}"
                        )
                        st.session_state.question_types_config[qtype]['questions'][i]['num_subparts'] = num_subparts
                        
                        # Multi-Part Type (Internal only, not in UI)
                        st.session_state.question_types_config[qtype]['questions'][i]['multipart_type'] = st.session_state.question_types_config[qtype]['questions'][i].get('multipart_type', 'Auto')
                        
                        # Initialize subparts config for this question
                        if 'subparts_config' not in st.session_state.question_types_config[qtype]['questions'][i]:
                            st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = []
                        
                        # Adjust list length
                        current_subparts = len(st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'])
                        if num_subparts != current_subparts:
                            if num_subparts > current_subparts:
                                for j in range(current_subparts, num_subparts):
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'].append({
                                        'part': chr(97 + j),
                                        'dok': 1,
                                        'marks': 1.0,
                                        'taxonomy': 'Remembering'
                                    })
                            else:
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'] = \
                                    st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][:num_subparts]
                        
                        # Render subpart inputs
                        for j in range(num_subparts):
                            cols = st.columns([1, 1, 1, 2])
                            
                            with cols[0]:
                                st.markdown(f"**Part ({chr(97 + j)})**")
                            
                            with cols[1]:
                                dok = st.selectbox(
                                    "DOK",
                                    [1, 2, 3],
                                    key=f"multipart_subpart_dok_{i}_{j}",
                                    index=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('dok', 1) - 1
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['dok'] = dok
                            
                            with cols[2]:
                                marks = st.number_input(
                                    "Marks",
                                    min_value=0.5,
                                    max_value=10.0,
                                    step=0.5,
                                    key=f"multipart_subpart_marks_{i}_{j}",
                                    value=st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('marks', 1.0)
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['marks'] = marks
                            
                            with cols[3]:
                                taxonomy = st.selectbox(
                                    "Taxonomy",
                                    taxonomy_options,
                                    key=f"multipart_subpart_taxonomy_{i}_{j}",
                                    index=taxonomy_options.index(
                                        st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j].get('taxonomy', 'Remembering')
                                    )
                                )
                                st.session_state.question_types_config[qtype]['questions'][i]['subparts_config'][j]['taxonomy'] = taxonomy
                        
                        st.markdown("---")

    # Generate button at the bottom of configuration
    st.markdown('<div class="section-header">Generate Questions</div>', unsafe_allow_html=True)
    
    if not gemini_api_key:
        st.warning("⚠️ Gemini API key is missing. Please add GEMINI_API_KEY to your .streamlit/secrets.toml.")
    else:
        
        if st.button("🚀 Generate All Questions", type="primary", use_container_width=True):
            if not chapter:
                st.error("❌ Please enter a chapter name")
            elif not st.session_state.question_types_config:
                st.error("❌ Please configure at least one question type")
            else:
                # Validate that all questions have topics
                missing_topics = []
                
                for qtype, config in st.session_state.question_types_config.items():
                    for i, q in enumerate(config.get('questions', []), 1):
                        if not q.get('topic', '').strip():
                            missing_topics.append(f"{qtype} Question {i}")
                
                if missing_topics:
                    st.error(f"❌ Please specify topics for: {', '.join(missing_topics)}")
                else:
                    # Prepare general config
                    config = {
                        'curriculum': curriculum,
                        'grade': grade,
                        'subject': subject,
                        'chapter': chapter,
                        'science_domain': science_domain,
                        'old_concept': old_concept,
                        'new_concept': new_concept,
                        'additional_notes': additional_notes,
                        'api_key': gemini_api_key,
                        'universal_pdf': st.session_state.get('universal_pdf'),  # Pass universal PDF
                        'core_skill_enabled': st.session_state.get('core_skill_enabled', False)  # Core skill extraction
                    }
                    
                    # Process each question type
                    questions_list = []
                    for qtype, type_config in st.session_state.question_types_config.items():
                        questions = type_config.get('questions', [])
                        for q in questions:
                            # Ensure type is set
                            q['type'] = qtype
                            questions_list.append(q)
                            
                            # Descriptive is now its own independent type — no auto-cloning from FIB.
                    
                    if questions_list:
                        # Run async pipeline
                        with st.spinner("🔄 Starting question generation pipeline..."):
                            try:
                                # Import here to avoid circular imports
                                from batch_processor import process_batches_pipeline
                                import nest_asyncio
                                nest_asyncio.apply()  # Prevent "event loop already running" error in Streamlit
                                
                                # Run async pipeline without progressive UI callback
                                # Results will be available in Results tab only
                                final_results = asyncio.run(
                                    process_batches_pipeline(
                                        questions_config=questions_list,
                                        general_config=config,
                                        progress_callback=None  # Disable progressive rendering
                                    )
                                )
                                
                                # Clear all duplicate-related session state keys before storing new results
                                # This prevents old duplicates from appearing with new questions
                                keys_to_remove = [key for key in st.session_state.keys() if key.startswith('duplicates_')]
                                for key in keys_to_remove:
                                    del st.session_state[key]
                                
                                # Also clear duplicate checkbox states
                                keys_to_remove = [key for key in st.session_state.keys() if key.startswith('duplicate_results_')]
                                for key in keys_to_remove:
                                    del st.session_state[key]
                                
                                keys_to_remove = [key for key in st.session_state.keys() if key.startswith('duplicate_count_results_')]
                                for key in keys_to_remove:
                                    del st.session_state[key]
                                
                                # Store final results
                                st.session_state.generated_output = final_results
                                
                                st.success("✅ All questions generated successfully! Go to the Results tab to view and manage them.")
                                
                            except Exception as e:
                                st.error(f"❌ Error during generation: {str(e)}")
                                st.exception(e)
                    else:
                        st.warning("No questions found to process.")
        # Progressive rendering already displays results during generation
        # No need to duplicate the display here anymore


with tab2:
    st.markdown('<div class="section-header">Previously Generated Questions</div>', unsafe_allow_html=True)

    # Display Persistent Generation Report (if any)
    if 'duplicate_generation_report' in st.session_state and st.session_state.duplicate_generation_report:
        report = st.session_state.duplicate_generation_report
        
        # Display summary
        st.markdown("### 📊 Generation Report")
        if report.get('success'):
            st.success(f"✅ Successfully generated duplicates for {report['success_count']} question(s).")
        
        if report.get('errors'):
            st.error(f"❌ Failed to generate duplicates for {len(report['errors'])} question(s).")
            for err in report['errors']:
                st.warning(f"• **{err['key']}**: {err['error']}")
        
        # Clear report button
        if st.button("Clear Report", key="clear_dup_report"):
            del st.session_state.duplicate_generation_report
            st.rerun()
        st.markdown("---")

    
    if st.session_state.generated_output:
        results = st.session_state.generated_output
        
        # Import renderer (if not already imported in scope, but safest to import here too if needed or rely on top level if used)
        from result_renderer import render_batch_results # Safe re-import inside function/block

        # Display results for each batch
        for batch_key, batch_result in results.items():
            with st.expander(f"📋 {batch_key}", expanded=True):
                
                # Extract raw and validated results
                raw_res = batch_result.get('raw', {})
                val_res = batch_result.get('validated', {})
                
                # Display Validated Content
                if val_res and not val_res.get('error'):
                        st.markdown("### ✅ Validated Output")
                        # Use the new renderer with "results" context
                        try:
                            render_batch_results(batch_key, val_res, render_context="results")
                        except Exception as render_err:
                            st.error(f"❌ Error rendering results for '{batch_key}': {str(render_err)}")
                            st.exception(render_err)
                            st.text_area("Raw Output (fallback)", value=val_res.get('text', ''), height=300, disabled=True)
                elif val_res and val_res.get('error'):
                        st.error(f"❌ Validation Error: {val_res['error']}")
                        st.error(val_res.get('text', ''))
                else:
                        st.warning("⚠️ Validation step missing or failed silently.")

                # Show Metadata
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Questions", raw_res.get('question_count', 'N/A'))
                with col2:
                    raw_time = raw_res.get('elapsed', 0)
                    val_time = val_res.get('elapsed', 0) if val_res else 0
                    st.metric("Total Time", f"{raw_time + val_time:.2f}s")

                # Expandable Raw Output
                with st.expander("Show Generated Version (Raw Backend Output)"):
                    st.text_area("Raw Generator Output", value=raw_res.get('text', 'No output'), height=300, disabled=True, key=f"raw_bak_{batch_key}")
                
                with st.expander("Show Validation Response (Raw Backend Output)"):
                    if val_res.get('error'):
                        st.error(f"Validation Error: {val_res['error']}")
                    st.text_area("Raw Validation Output", value=val_res.get('text', 'No output'), height=300, disabled=True, key=f"val_bak_{batch_key}")
        
        # Download option
        st.markdown("---")
        
        # Combine all results
        combined_output = ""
        for batch_key, batch_result in results.items():
            val_res = batch_result.get('validated', {})
            raw_res = batch_result.get('raw', {})
            final_text = val_res.get('text', '') if val_res else raw_res.get('text', 'Error')

            combined_output += f"\n\n{'='*80}\n"
            combined_output += f"BATCH: {batch_key}\n"
            combined_output += f"{'='*80}\n\n"
            combined_output += final_text
        
        st.download_button(
            label="📥 Download All Questions",
            data=combined_output,
            file_name="generated_questions.md",
            mime="text/markdown",
            use_container_width=True,
            key="download_inline_results"
        )
        
        # Add Regenerate Selected Section
        st.markdown("---")
        st.markdown('<div class="section-header">♻️ Regenerate Selected Questions</div>', unsafe_allow_html=True)
        
        # Check for regeneration selection
        regen_selection = st.session_state.get('regen_selection', set())
        
        if regen_selection:
            st.info(f"✅ {len(regen_selection)} question(s) selected for regeneration")
            
            # Show selected questions breakdown
            regen_map = {}
            for item in regen_selection:
                # Format: "batch_key:q_num"
                if ':' in item:
                    b_key, q_num = item.rsplit(':', 1)
                    if b_key not in regen_map:
                        regen_map[b_key] = []
                    regen_map[b_key].append(int(q_num))
            
            for b_key, indices in regen_map.items():
                st.write(f"• **{b_key}**: Questions {sorted(indices)}")
                
            if st.button("♻️ Regenerate Selected", type="primary", use_container_width=True):
                # Collect reasons for each selected question
                regeneration_reasons_map = {}
                
                for item in regen_selection:
                    if ':' in item:
                        b_key, q_num = item.rsplit(':', 1)
                        regen_reason_key = f"regen_reason_{b_key}_{q_num}"
                        reason = st.session_state.get(regen_reason_key, "").strip()
                        regeneration_reasons_map[item] = reason
                
                if not gemini_api_key:
                    st.error("❌ Gemini API key is missing in secrets.toml")
                else:
                    with st.spinner("Regenerating specific questions..."):
                        from batch_processor import regenerate_specific_questions_pipeline
                        from result_renderer import normalize_llm_output_to_questions
                        
                        # Prepare configurations
                        general_config = {
                            'api_key': gemini_api_key,
                            'additional_notes': additional_notes,
                            'universal_pdf': st.session_state.get('universal_pdf'),
                            'grade': st.session_state.get('grade', 'Grade 10'),
                            'curriculum': st.session_state.get('curriculum', 'NCERT'),
                            'subject': st.session_state.get('subject', 'Science'),
                            'chapter': st.session_state.get('chapter', 'Chapter'),
                            'science_domain': st.session_state.get('science_domain', 'Not Specified'),
                            'old_concept': st.session_state.get('old_concept', 'N/A'),
                            'new_concept': st.session_state.get('new_concept', 'N/A'),
                            'core_skill_enabled': st.session_state.get('core_skill_enabled', False)
                        }
                        
                        # Reconstruct the full original config list
                        # IMPORTANT: Must mirror the generation pipeline exactly,
                        # including the auto-generated Descriptive clone for every FIB question.
                        full_config_list = []
                        for q_type, config in st.session_state.question_types_config.items():
                            for q in config.get('questions', []):
                                q_copy = q.copy()
                                q_copy['type'] = q_type
                                full_config_list.append(q_copy)
                                
                                # Note: Descriptive is now its own independent question type with its own UI.
                                # No auto-cloning from FIB.
                        
                        # Build existing content map
                        existing_content_map = {}
                        if st.session_state.generated_output:
                            for b_key, b_res in st.session_state.generated_output.items():
                                val_res = b_res.get('validated', {})
                                text = val_res.get('text', '')
                                if text:
                                    q_map = normalize_llm_output_to_questions(text)
                                    existing_content_map[b_key] = q_map
                        
                        general_config['existing_content_map'] = existing_content_map
                        general_config['regeneration_reasons_map'] = regeneration_reasons_map

                        # Run regeneration
                        import asyncio
                        try:
                            # Use internal helper to run async in streamlit
                            import nest_asyncio
                            nest_asyncio.apply()
                            
                            regen_results = asyncio.run(regenerate_specific_questions_pipeline(
                                original_config=full_config_list,
                                regeneration_map=regen_map,
                                general_config=general_config
                            ))
                            
                            if isinstance(regen_results, dict) and regen_results.get('error'):
                                st.error(f"❌ Regeneration failed: {regen_results['error']}")
                            else:
                                # Merge results back into st.session_state.generated_output
                                merged_count = 0
                                
                                for batch_key, batch_res in regen_results.items():
                                    val_res = batch_res.get('validated', {})
                                    new_text_content = val_res.get('text', '')
                                    
                                    if new_text_content and batch_key in st.session_state.generated_output:
                                        # Parse existing content
                                        existing_text = st.session_state.generated_output[batch_key]['validated']['text']
                                        existing_questions_map = normalize_llm_output_to_questions(existing_text)
                                        
                                        # Parse new content
                                        new_questions_map = normalize_llm_output_to_questions(new_text_content)
                                        
                                        # Get requested indices for this batch
                                        requested_indices = sorted(regen_map.get(batch_key, []))
                                        
                                        # Sort new keys to align with requested indices
                                        import re
                                        sorted_new_keys = sorted(new_questions_map.keys(), 
                                            key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
                                            
                                        # Replace questions at requested indices
                                        for i, new_k in enumerate(sorted_new_keys):
                                            if i < len(requested_indices):
                                                original_idx = requested_indices[i]
                                                original_k = f"question{original_idx}"
                                                existing_questions_map[original_k] = new_questions_map[new_k]
                                                merged_count += 1
                                        
                                        # Serialize back to the same format as the original LLM output
                                        # The format should be a JSON object where each questionX key maps to a markdown string
                                        # CRITICAL: We don't use json.dumps here because it escapes newlines (\n -> \\n)
                                        # which causes them to display as literal text instead of actual line breaks
                                        import json
                                        
                                        # Manually construct JSON string with proper newline preservation
                                        # Each value still needs JSON string escaping (quotes, backslashes, etc.)
                                        # but we do it in a way that preserves the actual newlines
                                        json_parts = []
                                        for q_key in sorted(existing_questions_map.keys(), 
                                                           key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0):
                                            # JSON-escape the key and value properly
                                            # We escape quotes and backslashes, but keep newlines as actual newlines
                                            escaped_value = existing_questions_map[q_key].replace('\\', '\\\\').replace('"', '\\"')
                                            json_parts.append(f'  "{q_key}": "{escaped_value}"')
                                        
                                        updated_json_str = "{\n" + ",\n".join(json_parts) + "\n}"
                                        
                                        # Create a new batch result to trigger Streamlit's change detection
                                        # Direct mutation of nested dicts may not trigger rerender
                                        updated_batch_result = st.session_state.generated_output[batch_key].copy()
                                        updated_batch_result['validated'] = updated_batch_result['validated'].copy()
                                        updated_batch_result['validated']['text'] = updated_json_str
                                        st.session_state.generated_output[batch_key] = updated_batch_result
                                        
                                if merged_count > 0:
                                    st.success(f"✅ Regenerated {merged_count} question(s) successfully!")
                                    st.session_state.regen_selection = set()
                                    st.rerun()
                                else:
                                    st.error("❌ No questions were successfully merged. Please try again.")
                                    
                        except Exception as e:
                            st.error(f"❌ Error during regeneration: {str(e)}")
                            st.exception(e)
        else:
            st.info("ℹ️ Select questions above using the checkboxes to regenerate specific items.")

        # Add Generate Duplicates section
        st.markdown("---")
        st.markdown('<div class="section-header">🔄 Generate Question Duplicates</div>', unsafe_allow_html=True)
        
        # Collect selected questions from checkbox states
        selected_questions = {}
        
        # Iterate through all rendered questions and check their checkbox states
        for batch_key, batch_result in results.items():
            val_res = batch_result.get('validated', {})
            text_content = val_res.get('text', '')
            
            if text_content:
                # Extract JSON to get question keys
                from result_renderer import extract_json_objects
                json_objects = extract_json_objects(text_content)
                
                for obj in json_objects:
                    # Handle validation wrapper
                    questions_to_check = {}
                    if 'CORRECTED_ITEM' in obj or 'corrected_item' in obj:
                        corrected = obj.get('CORRECTED_ITEM') or obj.get('corrected_item')
                        if isinstance(corrected, dict):
                            questions_to_check = corrected
                    else:
                        questions_to_check = obj
                    
                    # Check each question
                    for q_key, q_content in questions_to_check.items():
                        if q_key.lower().startswith('question') or q_key.lower().startswith('q'):
                            checkbox_key = f"duplicate_results_{batch_key}_{q_key}"
                            count_key = f"duplicate_count_results_{batch_key}_{q_key}"
                            
                            if st.session_state.get(checkbox_key, False):
                                q_num = q_key.replace("question", "").replace("q", "")
                                question_code = f"{batch_key}_q{q_num}" if q_num else f"{batch_key}_{q_key}"
                                
                                selected_questions[f"{batch_key}_{q_key}"] = {
                                    'question_key': q_key,
                                    'question_code': question_code,
                                    'batch_key': batch_key,
                                    'markdown_content': q_content if isinstance(q_content, str) else str(q_content),
                                    'num_duplicates': st.session_state.get(count_key, 1),
                                    'additional_notes': st.session_state.get(f"duplicate_notes_{batch_key}_{q_key}", ""),
                                    'pdf_file': st.session_state.get(f"duplicate_file_{batch_key}_{q_key}", None)
                                }
        
        if selected_questions:
            st.info(f"✅ {len(selected_questions)} question(s) selected for duplication")
            
            with st.expander("View Selected Questions", expanded=False):
                for key, data in selected_questions.items():
                    st.write(f"• {data['batch_key']} - {data['question_key']} (x{data['num_duplicates']})")
            
            if st.button("🚀 Generate Duplicates", type="primary", use_container_width=True):
                if not gemini_api_key:
                    st.error("❌ Gemini API key is missing in secrets.toml")
                else:
                    with st.spinner("Generating duplicates... This may take a moment."):
                        requests = []
                        for key, data in selected_questions.items():
                            requests.append({
                                'original_markdown': data['markdown_content'],
                                'variation_count': data['num_duplicates'],
                                'custom_notes': data.get('additional_notes', ''),
                                'context_file': data.get('pdf_file')
                            })
                        
                        try:
                            # Run async parallel duplication
                            dup_results_list = asyncio.run(process_parallel_duplication(requests, gemini_api_key))
                            
                            report = {
                                'success': False,
                                'success_count': 0,
                                'errors': []
                            }
                            
                            # Map results back to selected questions
                            question_keys = list(selected_questions.keys())
                            for i, result in enumerate(dup_results_list):
                                key = question_keys[i]
                                data = selected_questions[key]
                                
                                if result.get('error'):
                                    report['errors'].append({
                                        'key': data['question_code'],
                                        'error': result['error']
                                    })
                                else:
                                    duplicates = result.get('duplicates', [])
                                    if not duplicates:
                                        report['errors'].append({
                                            'key': data['question_code'],
                                            'error': "AI returned no duplicates. Try adjusting notes or file context."
                                        })
                                    else:
                                        duplicates_key = f"duplicates_{data['batch_key']}_{data['question_key']}"
                                        st.session_state[duplicates_key] = duplicates
                                        report['success_count'] += 1
                            
                            report['success'] = report['success_count'] > 0
                            st.session_state.duplicate_generation_report = report
                            
                            st.info("Generation complete. Reloading...")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Error during duplication: {str(e)}")
                            st.exception(e)
        else:
            st.info("ℹ️ Select questions using the checkboxes above to generate duplicates")
    else:
        st.info("👈 Configure and generate questions to see results here")


# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #6b7280; padding: 1rem;">
    <p>Built with ❤️ using Streamlit and Gemini AI</p>
</div>
""", unsafe_allow_html=True)
