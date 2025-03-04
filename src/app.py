import os
import traceback
import streamlit as st
from utils.get_urls import scrape_urls
from langchain_core.messages import AIMessage, HumanMessage
from langchain_community.document_loaders import WebBaseLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from langchain_community.llms import HuggingFaceHub
import PyPDF2
from langchain_core.documents import Document

# Load environment variables
load_dotenv()
HF_TOKEN = os.getenv('HUGGINGFACEHUB_API_TOKEN') 
# HF_TOKEN = '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'


# Define function to create vector store from URL
def get_vectorstore_from_url(url, max_depth, pdf_text=None):
    try:
        if not os.path.exists('src/chroma'):
            os.makedirs('src/chroma')
        if not os.path.exists('src/scrape'):
            os.makedirs('src/scrape')

        documents = []
        if url:
            urls = scrape_urls(url, max_depth)
            loader = WebBaseLoader(urls)
            documents = loader.load()

        if pdf_text:
            documents.append(Document(page_content=pdf_text, metadata={"source": "uploaded_pdf"}))

        # Split text into smaller chunks for better context alignment
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=50)
        document_chunks = text_splitter.split_documents(documents)

        # Create embeddings using a more robust model
        embedding = HuggingFaceInferenceAPIEmbeddings(
            api_key= HF_TOKEN,
            model_name="sentence-transformers/multi-qa-mpnet-base-dot-v1"
        )
        vector_store = Chroma.from_documents(document_chunks, embedding)
        return vector_store, len(document_chunks)
    except Exception as e:
        st.error(f"An error occurred during processing: {e}")
        traceback.print_exc()
        return None, 0

# Define function to create context retriever chain
def get_context_retriever_chain(vector_store):
    llm = HuggingFaceHub(
        repo_id="HuggingFaceH4/zephyr-7b-alpha",
        model_kwargs={"temperature": 0.7, "max_new_tokens": 512, "max_length": 64},
    )

    retriever = vector_store.as_retriever(
        search_kwargs={"k": 5}  # Limiting to top 5 results for better relevance
    )

    prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user", "Based on the conversation and the content retrieved, generate a relevant and accurate response.")
    ])

    retriever_chain = create_history_aware_retriever(llm, retriever, prompt)
    return retriever_chain

# Define function to create conversational RAG chain
def get_conversational_rag_chain(retriever_chain):
    llm = HuggingFaceHub(
        repo_id="HuggingFaceH4/zephyr-7b-alpha",
        model_kwargs={"temperature": 0.7, "max_new_tokens": 512, "max_length": 64},
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert assistant with over 50 years of experience. Provide detailed, concise, and accurate answers based on the user's input and the available context."),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        ("system", "Context: {context}"),
        ("human", "Answer:")
    ])

    stuff_documents_chain = create_stuff_documents_chain(llm, prompt)
    conversation_rag_chain = create_retrieval_chain(retriever_chain, stuff_documents_chain)
    return conversation_rag_chain

# Define function to get response
def get_response(user_input):
    retriever_chain = get_context_retriever_chain(st.session_state.vector_store)
    conversation_rag_chain = get_conversational_rag_chain(retriever_chain)

    response = conversation_rag_chain.invoke({
        "chat_history": st.session_state.chat_history,
        "input": user_input
    })

    ai_response = response['answer'].split("Answer:", 1)[-1].strip()
    return ai_response

# Streamlit app configuration
st.set_page_config(page_title="WEB-AI 🤖: Chat With Websites", page_icon="🤖")
st.title("WEB-AI 🤖: Your Web Assistant")

# Custom CSS for styling
def custom_css():
    st.markdown('''
        <style>
            .chat-history {
                max-height: 70vh;
                overflow-y: auto;
                padding: 1rem;
                border: 1px solid #e0e0e0;
                # background-color: #fafafa;
                border-radius: 10px;
            }
            .user-input {
                border: 1px solid #e0e0e0;
                padding: 0.5rem;
                border-radius: 5px;
                margin-top: 10px;
            }
            .loading {
                color: #ff9800;
            }
            .chat-message {
                margin: 10px 0;
                # color: black; /* Set default text color to black */
            }
            .chat-message.ai {
                # background-color: #e1f5fe;
                border-radius: 10px;
                padding: 10px;
                # color: black; /* Set AI message text color to black */
            }
            .chat-message.human {
                background-color: #e1f5fe;
                border-radius: 10px;
                padding: 10px;
                text-align: right;
                color: black; /* Set human message text color to black */
            }
        </style>
    ''', unsafe_allow_html=True)

custom_css()

# Initialize session state
if "freeze" not in st.session_state:
    st.session_state.freeze = False
if "max_depth" not in st.session_state:
    st.session_state.max_depth = 1
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "len_urls" not in st.session_state:
    st.session_state.len_urls = 0

def extract_text_from_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page_num in range(len(pdf_reader.pages)):
        page = pdf_reader.pages[page_num]
        text += page.extract_text() if page.extract_text() else ""
    return text

# Sidebar configuration
with st.sidebar:
    st.header("WEB-AI 🤖")
    website_url = st.text_input("Website URL (optional)")

    st.title("PDF Uploader")
    uploaded_file = st.file_uploader("Upload a PDF file (optional)", type=["pdf"])

    st.session_state.max_depth = st.slider("Select maximum scraping depth:", 1, 5, 1, disabled=st.session_state.freeze)
    if st.button("Proceed", disabled=st.session_state.freeze):
        st.session_state.freeze = True

    pdf_text = None
    if uploaded_file is not None:
        st.write(f"Uploaded file: {uploaded_file.name}")
        pdf_text = extract_text_from_pdf(uploaded_file)

# Main app logic
if website_url or pdf_text:
    if st.session_state.freeze:
        if st.session_state.vector_store is None:
            with st.spinner("Processing content..."):
                st.session_state.vector_store, st.session_state.len_docs = get_vectorstore_from_url(website_url, st.session_state.max_depth, pdf_text)
                if st.session_state.vector_store:
                    st.success(f"Processing completed! Total Documents: {st.session_state.len_docs}")
                else:
                    st.error("Failed to create vector store.")
                    st.session_state.freeze = False
        else:
            st.sidebar.success(f"Total Documents Processed: {st.session_state.len_docs}")

        user_query = st.chat_input("Type your message here...")
        if user_query:
            response = get_response(user_query)
            st.session_state.chat_history.append(HumanMessage(content=user_query))
            st.session_state.chat_history.append(AIMessage(content=response))

        # Display chat history
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.chat_history:
                if isinstance(message, AIMessage):
                    st.markdown(f'<div class="chat-message ai">{message.content}</div>', unsafe_allow_html=True)
                elif isinstance(message, HumanMessage):
                    st.markdown(f'<div class="chat-message human">{message.content}</div>', unsafe_allow_html=True)

# Sidebar footer
with st.sidebar:
    st.markdown('---')
    st.markdown('Connect with me:')
    st.markdown('[LinkedIn](linkedin.com/in/satyam-jain-76290521b)')
    st.markdown('[GitHub](https://github.com/satyamgits07)')
    st.markdown('[Email](mailto:jainsatyam503@gmail.com)')