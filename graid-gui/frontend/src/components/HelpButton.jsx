import React, { useState, useEffect } from 'react';

const HelpButton = ({ title, content, language, setLanguage }) => {
    const [isOpen, setIsOpen] = useState(false);

    // Close modal on outside click or Esc key
    useEffect(() => {
        const handleEsc = (e) => {
            if (e.key === 'Escape') setIsOpen(false);
        };
        if (isOpen) {
            window.addEventListener('keydown', handleEsc);
        }
        return () => window.removeEventListener('keydown', handleEsc);
    }, [isOpen]);

    const toggleModal = (e) => {
        e.stopPropagation();
        setIsOpen(!isOpen);
    };

    return (
        <>
            <button
                className="help-trigger-btn"
                onClick={toggleModal}
                title="說明"
            >
                ?
            </button>

            {isOpen && (
                <div className="help-modal-overlay" onClick={() => setIsOpen(false)}>
                    <div className="help-modal-content" onClick={(e) => e.stopPropagation()}>
                        <div className="help-modal-header">
                            <h3>{title}</h3>
                            <button className="help-modal-close" onClick={() => setIsOpen(false)}>&times;</button>
                        </div>
                        <div className="help-modal-body">
                            <div className="modal-language-switcher">
                                {['EN', 'CN', 'TW'].map(lang => (
                                    <button
                                        key={lang}
                                        className={`modal-lang-btn ${language === lang ? 'active' : ''}`}
                                        onClick={() => setLanguage(lang)}
                                    >
                                        {lang}
                                    </button>
                                ))}
                            </div>
                            <div className="help-divider"></div>
                            {content.sections.map((section, idx) => (
                                <div key={idx} className="help-section">
                                    <h4>{section.header}</h4>
                                    <p>{section.content}</p>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default HelpButton;
