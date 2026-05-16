import React, { useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import axios from 'axios';
import toast from 'react-hot-toast';
import {
  ChatBubbleLeftRightIcon,
  PaperAirplaneIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline';

const API_URL = process.env.REACT_APP_API_URL || '/api';

const AIChatbox = () => {
  const { token } = useSelector((state) => state.auth);
  const currentOrganization = useSelector((state) => state.organization.currentOrganization);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: 'Hi, I am the project assistant. Ask me about APIs, datasets, deployment, policies, membership plans, or how to run the app.',
    },
  ]);

  const headers = useMemo(() => {
    const result = { 'Content-Type': 'application/json' };
    if (token) {
      result.Authorization = `Bearer ${token}`;
    }
    return result;
  }, [token]);

  const sendMessage = async (customMessage) => {
    const message = (customMessage || input).trim();
    if (!message || loading) return;

    const nextMessages = [...messages, { role: 'user', text: message }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);

    try {
      const response = await axios.post(
        `${API_URL}/assistant/chat`,
        {
          message,
          organization_id: currentOrganization?.id || null,
        },
        { headers }
      );
      setMessages([
        ...nextMessages,
        { role: 'assistant', text: response.data.reply },
      ]);
    } catch (error) {
      toast.error('Assistant is currently unavailable');
      setMessages([
        ...nextMessages,
        {
          role: 'assistant',
          text: 'I could not reach the assistant backend right now. Please make sure the Flask server is running.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const quickPrompt = (prompt) => {
    setInput(prompt);
    sendMessage(prompt);
  };

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {open && (
        <div className="w-[360px] sm:w-[400px] h-[520px] mb-4 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col overflow-hidden">
          <div className="px-4 py-3 bg-primary-600 text-white flex items-center justify-between">
            <div>
              <p className="font-semibold">AI Assistant</p>
              <p className="text-xs text-white/80">Project help and quick guidance</p>
            </div>
            <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-white/10">
              <XMarkIcon className="w-5 h-5" />
            </button>
          </div>
          <div className="flex-1 p-4 space-y-3 overflow-auto bg-gray-50 dark:bg-gray-900">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
                    message.role === 'user'
                      ? 'bg-primary-600 text-white'
                      : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 border border-gray-200 dark:border-gray-700'
                  }`}
                >
                  {message.text}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl px-4 py-3 text-sm bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-700">
                  Thinking...
                </div>
              </div>
            )}
          </div>
          <div className="p-3 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
            <div className="grid grid-cols-2 gap-2 mb-3">
              {[
                'Show the APIs used',
                'Explain deployment',
                'Show membership plans',
                'How to run locally',
              ].map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => quickPrompt(prompt)}
                  className="text-xs text-left rounded-lg px-3 py-2 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage();
              }}
              className="flex items-center gap-2"
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask something about the project..."
                className="flex-1 input-field text-sm"
              />
              <button
                type="submit"
                className="btn-primary px-3 py-2 inline-flex items-center justify-center"
                disabled={loading}
              >
                <PaperAirplaneIcon className="w-5 h-5" />
              </button>
            </form>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen(!open)}
        className="w-14 h-14 rounded-full shadow-lg bg-primary-600 text-white flex items-center justify-center hover:bg-primary-700 transition-colors"
        aria-label="Open AI assistant"
      >
        <ChatBubbleLeftRightIcon className="w-7 h-7" />
      </button>
    </div>
  );
};

export default AIChatbox;
