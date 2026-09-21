(() => {
    "use strict";

    const UI = {
        de: {
            button: "E Mail Benachrichtigungen",
            title: "E Mail Benachrichtigungen",
            intro: "Benachrichtigungen bei Laufwerksfehlern, kritischen SMART Werten, RAID Problemen oder hoher Temperatur.",
            enabled: "E Mail Benachrichtigungen aktivieren",
            smtpServer: "SMTP Server",
            smtpPort: "SMTP Port",
            encryption: "Verschlüsselung",
            starttls: "STARTTLS",
            sslTls: "SSL/TLS",
            none: "Keine",
            username: "Benutzername",
            password: "Passwort",
            passwordSaved: "Gespeichertes Passwort bleibt erhalten",
            sender: "Absenderadresse",
            recipient: "Empfängeradresse",
            emailLanguage: "E Mail Sprache",
            report: "Bericht",
            reportOff: "Aus",
            reportWeekly: "Wöchentlich",
            reportMonthly: "Monatlich",
            report3Months: "Alle 3 Monate",
            report6Months: "Alle 6 Monate",
            report9Months: "Alle 9 Monate",
            reportYearly: "Jährlich",
            autoLanguage: "Automatisch wie Disk Monitor",
            temperatureLimit: "Temperaturwarnung ab",
            events: "Benachrichtigungen",
            smartHealth: "SMART Fehler",
            smartAttributes: "Kritische SMART Werte verändert",
            missingDrive: "Laufwerk nicht mehr erkannt",
            raid: "RAID Fehler",
            temperature: "Temperaturwarnung",
            recovery: "Entwarnung senden",
            test: "Test E Mail senden",
            save: "Speichern",
            close: "Schließen",
            loading: "Einstellungen werden geladen …",
            saved: "Einstellungen gespeichert.",
            testSent: "Test E Mail wurde gesendet.",
            failed: "Aktion fehlgeschlagen.",
            configured: "Eingerichtet",
            disabled: "Deaktiviert",
            sendFailed: "Letzter Versand fehlgeschlagen",
            noPassword: "Passwort noch nicht gespeichert"
        },
        en: {
            button: "Email notifications",
            title: "Email notifications",
            intro: "Notifications for drive failures, critical SMART values, RAID problems or high temperature.",
            enabled: "Enable email notifications",
            smtpServer: "SMTP server",
            smtpPort: "SMTP port",
            encryption: "Encryption",
            starttls: "STARTTLS",
            sslTls: "SSL/TLS",
            none: "None",
            username: "Username",
            password: "Password",
            passwordSaved: "Saved password will be kept",
            sender: "Sender address",
            recipient: "Recipient address",
            emailLanguage: "Email language",
            report: "Report",
            reportOff: "Off",
            reportWeekly: "Weekly",
            reportMonthly: "Monthly",
            report3Months: "Every 3 months",
            report6Months: "Every 6 months",
            report9Months: "Every 9 months",
            reportYearly: "Yearly",
            autoLanguage: "Automatic like Disk Monitor",
            temperatureLimit: "Temperature warning from",
            events: "Notifications",
            smartHealth: "SMART errors",
            smartAttributes: "Critical SMART values changed",
            missingDrive: "Drive no longer detected",
            raid: "RAID errors",
            temperature: "Temperature warning",
            recovery: "Send recovery message",
            test: "Send test email",
            save: "Save",
            close: "Close",
            loading: "Loading settings …",
            saved: "Settings saved.",
            testSent: "Test email was sent.",
            failed: "Action failed.",
            configured: "Configured",
            disabled: "Disabled",
            sendFailed: "Last delivery failed",
            noPassword: "No password saved yet"
        },
        fr: {
            button: "Notifications e mail",
            title: "Notifications e mail",
            intro: "Notifications en cas de panne de disque, valeurs SMART critiques, problèmes RAID ou température élevée.",
            enabled: "Activer les notifications e mail",
            smtpServer: "Serveur SMTP",
            smtpPort: "Port SMTP",
            encryption: "Chiffrement",
            starttls: "STARTTLS",
            sslTls: "SSL/TLS",
            none: "Aucun",
            username: "Nom d’utilisateur",
            password: "Mot de passe",
            passwordSaved: "Le mot de passe enregistré sera conservé",
            sender: "Adresse expéditeur",
            recipient: "Adresse destinataire",
            emailLanguage: "Langue des e mails",
            report: "Rapport",
            reportOff: "Désactivé",
            reportWeekly: "Hebdomadaire",
            reportMonthly: "Mensuel",
            report3Months: "Tous les 3 mois",
            report6Months: "Tous les 6 mois",
            report9Months: "Tous les 9 mois",
            reportYearly: "Annuel",
            autoLanguage: "Automatique comme Disk Monitor",
            temperatureLimit: "Alerte de température à partir de",
            events: "Notifications",
            smartHealth: "Erreurs SMART",
            smartAttributes: "Valeurs SMART critiques modifiées",
            missingDrive: "Disque non détecté",
            raid: "Erreurs RAID",
            temperature: "Alerte de température",
            recovery: "Envoyer le retour à la normale",
            test: "Envoyer un e mail de test",
            save: "Enregistrer",
            close: "Fermer",
            loading: "Chargement des paramètres …",
            saved: "Paramètres enregistrés.",
            testSent: "E mail de test envoyé.",
            failed: "Échec de l’action.",
            configured: "Configuré",
            disabled: "Désactivé",
            sendFailed: "Dernier envoi échoué",
            noPassword: "Aucun mot de passe enregistré"
        },
        pt: {
            button: "Notificações por e mail",
            title: "Notificações por e mail",
            intro: "Notificações para falhas de unidades, valores SMART críticos, problemas RAID ou temperatura elevada.",
            enabled: "Ativar notificações por e mail",
            smtpServer: "Servidor SMTP",
            smtpPort: "Porta SMTP",
            encryption: "Encriptação",
            starttls: "STARTTLS",
            sslTls: "SSL/TLS",
            none: "Nenhuma",
            username: "Utilizador",
            password: "Palavra passe",
            passwordSaved: "A palavra passe guardada será mantida",
            sender: "Endereço do remetente",
            recipient: "Endereço do destinatário",
            emailLanguage: "Idioma do e mail",
            report: "Relatório",
            reportOff: "Desativado",
            reportWeekly: "Semanal",
            reportMonthly: "Mensal",
            report3Months: "A cada 3 meses",
            report6Months: "A cada 6 meses",
            report9Months: "A cada 9 meses",
            reportYearly: "Anual",
            autoLanguage: "Automático como o Disk Monitor",
            temperatureLimit: "Aviso de temperatura a partir de",
            events: "Notificações",
            smartHealth: "Erros SMART",
            smartAttributes: "Valores SMART críticos alterados",
            missingDrive: "Unidade deixou de ser detetada",
            raid: "Erros RAID",
            temperature: "Aviso de temperatura",
            recovery: "Enviar mensagem de normalização",
            test: "Enviar e mail de teste",
            save: "Guardar",
            close: "Fechar",
            loading: "A carregar definições …",
            saved: "Definições guardadas.",
            testSent: "E mail de teste enviado.",
            failed: "A ação falhou.",
            configured: "Configurado",
            disabled: "Desativado",
            sendFailed: "Último envio falhou",
            noPassword: "Ainda não existe palavra passe guardada"
        },
        es: {
            button: "Notificaciones por correo",
            title: "Notificaciones por correo",
            intro: "Notificaciones por fallos de unidades, valores SMART críticos, problemas RAID o temperatura alta.",
            enabled: "Activar notificaciones por correo",
            smtpServer: "Servidor SMTP",
            smtpPort: "Puerto SMTP",
            encryption: "Cifrado",
            starttls: "STARTTLS",
            sslTls: "SSL/TLS",
            none: "Ninguno",
            username: "Usuario",
            password: "Contraseña",
            passwordSaved: "La contraseña guardada se conservará",
            sender: "Dirección del remitente",
            recipient: "Dirección del destinatario",
            emailLanguage: "Idioma del correo",
            report: "Informe",
            reportOff: "Desactivado",
            reportWeekly: "Semanal",
            reportMonthly: "Mensual",
            report3Months: "Cada 3 meses",
            report6Months: "Cada 6 meses",
            report9Months: "Cada 9 meses",
            reportYearly: "Anual",
            autoLanguage: "Automático como Disk Monitor",
            temperatureLimit: "Aviso de temperatura desde",
            events: "Notificaciones",
            smartHealth: "Errores SMART",
            smartAttributes: "Valores SMART críticos modificados",
            missingDrive: "Unidad ya no detectada",
            raid: "Errores RAID",
            temperature: "Aviso de temperatura",
            recovery: "Enviar recuperación",
            test: "Enviar correo de prueba",
            save: "Guardar",
            close: "Cerrar",
            loading: "Cargando ajustes …",
            saved: "Ajustes guardados.",
            testSent: "Correo de prueba enviado.",
            failed: "La acción ha fallado.",
            configured: "Configurado",
            disabled: "Desactivado",
            sendFailed: "El último envío falló",
            noPassword: "Todavía no hay contraseña guardada"
        }
    };

    let settings = null;
    let busy = false;

    function language() {
        const lang = String(document.documentElement.lang || "en").toLowerCase().split("-")[0];
        return UI[lang] ? lang : "en";
    }

    function text(key) {
        const lang = language();
        return (UI[lang] && UI[lang][key]) || UI.en[key] || key;
    }

    function injectStyle() {
        if (document.getElementById("dmEmailNotificationStyles")) return;
        const style = document.createElement("style");
        style.id = "dmEmailNotificationStyles";
        style.textContent = `
            #emailNotificationsButton {
                width: 40px;
                height: 40px;
                flex: 0 0 40px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                padding: 0;
                border: 0;
                border-radius: 7px;
                background: transparent;
                color: #c8d2dc;
                position: relative;
                margin-left: auto;
                margin-right: 0;
                transition: color .14s ease;
            }
            #emailNotificationsButton + #settingsButton {
                margin-left: 0 !important;
            }
            #emailNotificationsButton:hover,
            #emailNotificationsButton:focus-visible {
                background: transparent;
                color: #7fb2ff;
                outline: none;
            }
            #emailNotificationsButton svg {
                width: 25px;
                height: 25px;
                display: block;
            }
            #emailNotificationsButton .dm-email-status-dot {
                position: absolute;
                right: 5px;
                top: 5px;
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: #718091;
                box-shadow: 0 0 0 2px #18222d;
            }
            #emailNotificationsButton.dm-email-active .dm-email-status-dot {
                background: #43c17c;
                box-shadow: 0 0 7px rgba(67,193,124,.8), 0 0 0 2px #18222d;
            }
            #emailNotificationsButton.dm-email-error .dm-email-status-dot {
                background: #e06363;
                box-shadow: 0 0 7px rgba(224,99,99,.75), 0 0 0 2px #18222d;
            }
            #dmEmailOverlay {
                display: none;
                position: fixed;
                inset: 0;
                z-index: 330;
                align-items: center;
                justify-content: center;
                padding: 24px;
                background: rgba(3,8,13,.76);
                backdrop-filter: blur(3px);
            }
            #dmEmailOverlay.visible { display: flex; }
            .dm-email-dialog {
                width: min(720px, calc(100vw - 48px));
                max-height: min(88vh, 860px);
                display: flex;
                flex-direction: column;
                overflow: hidden;
                border: 1px solid rgba(91,156,255,.52);
                border-radius: 14px;
                background: #17222c;
                box-shadow: 0 24px 70px rgba(0,0,0,.62);
                color: #d7e0e8;
            }
            .dm-email-head {
                display: grid;
                grid-template-columns: 44px minmax(0,1fr) 40px;
                align-items: center;
                gap: 12px;
                padding: 18px 20px;
                border-bottom: 1px solid rgba(91,156,255,.52);
                background: #1d2a36;
            }
            .dm-email-head-icon {
                width: 42px;
                height: 42px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border: 1px solid rgba(91,156,255,.34);
                border-radius: 10px;
                background: rgba(91,156,255,.08);
                color: #a9c9ff;
            }
            .dm-email-head-icon svg { width: 24px; height: 24px; }
            .dm-email-title { margin: 0; color: #edf4f8; font-size: 18px; font-weight: 760; }
            .dm-email-intro { margin: 4px 0 0; color: #8fa2b5; font-size: 11.5px; line-height: 1.4; }
            .dm-email-close {
                width: 25px !important;
                height: 25px !important;
                min-width: 25px !important;
                flex: 0 0 25px !important;
                position: relative !important;
                justify-self: end;
                padding: 0 !important;
                border: 0 !important;
                border-radius: 6px !important;
                background: transparent !important;
                box-shadow: none !important;
                color: #9baab4 !important;
                font-size: 0 !important;
                line-height: 0 !important;
                cursor: pointer !important;
            }
            .dm-email-close::before,
            .dm-email-close::after {
                content: "" !important;
                position: absolute !important;
                left: 50% !important;
                top: 50% !important;
                width: 12px !important;
                height: 1.4px !important;
                margin: 0 !important;
                padding: 0 !important;
                border: 0 !important;
                border-radius: 0 !important;
                background: #9baab4 !important;
                transform-origin: center !important;
                box-shadow: none !important;
            }
            .dm-email-close::before {
                transform: translate(-50%,-50%) rotate(45deg) !important;
            }
            .dm-email-close::after {
                transform: translate(-50%,-50%) rotate(-45deg) !important;
            }
            .dm-email-close:hover,
            .dm-email-close:focus-visible {
                border: 0 !important;
                background: rgba(55,126,204,.18) !important;
                box-shadow: none !important;
                outline: none !important;
            }
            .dm-email-close:hover::before,
            .dm-email-close:hover::after,
            .dm-email-close:focus-visible::before,
            .dm-email-close:focus-visible::after {
                background: #a9d5ff !important;
            }
            .dm-email-body { padding: 18px 20px 20px; overflow-y: auto; scrollbar-width: thin; }
            .dm-email-enable-row {
                display: flex; align-items: center; justify-content: space-between; gap: 18px;
                padding: 12px 14px; margin-bottom: 15px; border: 1px solid rgba(91,156,255,.52);
                border-radius: 10px; background: rgba(16,28,39,.62);
            }
            .dm-email-enable-row label { color: #edf4f8; font-size: 13px; font-weight: 760; }
            .dm-email-switch { width: 38px; height: 22px; accent-color: #5b9cff; }
            .dm-email-grid { display: grid; grid-template-columns: 1fr 150px; gap: 12px; }
            .dm-email-field { min-width: 0; }
            .dm-email-field.dm-wide { grid-column: 1 / -1; }
            .dm-email-address-row {
                grid-column: 1 / -1;
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                gap: 12px;
            }
            .dm-email-preferences-row {
                grid-column: 1 / -1;
                display: grid;
                grid-template-columns: minmax(0, .92fr) minmax(0, .98fr) minmax(0, .82fr);
                gap: 12px;
            }
            .dm-email-field label, .dm-email-section-title {
                display: block; margin-bottom: 6px; color: #8fa2b5; font-size: 10.5px; font-weight: 700;
            }
            .dm-email-field input, .dm-email-field select {
                width: 100%; min-height: 38px; box-sizing: border-box; border: 1px solid rgba(91,156,255,.52);
                border-radius: 7px; background: #0d151d; color: #d7e0e8; padding: 8px 10px; outline: none;
                transition: border-color .14s ease, box-shadow .14s ease, background .14s ease;
            }
            .dm-email-field input:hover, .dm-email-field select:hover { border-color: rgba(91,156,255,.68); }
            .dm-email-field input:focus, .dm-email-field select:focus {
                border-color: rgba(91,156,255,.82);
                box-shadow: 0 0 0 1px rgba(91,156,255,.14);
            }
            .dm-email-number-wrap {
                position: relative;
                width: 100%;
            }
            #dmSmtpPort {
                padding-right: 34px;
                -moz-appearance: textfield;
            }
            #dmSmtpPort::-webkit-outer-spin-button,
            #dmSmtpPort::-webkit-inner-spin-button {
                -webkit-appearance: none;
                margin: 0;
            }
            .dm-email-number-controls {
                position: absolute;
                top: 1px;
                right: 1px;
                bottom: 1px;
                width: 29px;
                display: grid;
                grid-template-rows: 1fr 1fr;
                overflow: hidden;
                border-left: 1px solid rgba(91,156,255,.52);
                border-radius: 0 6px 6px 0;
                background: #0d151d;
            }
            .dm-email-number-button {
                display: flex;
                align-items: center;
                justify-content: center;
                min-width: 0;
                min-height: 0;
                padding: 0;
                border: 0;
                background: transparent;
                color: #7fb2ff;
                cursor: pointer;
            }
            .dm-email-number-button + .dm-email-number-button {
                border-top: 1px solid rgba(91,156,255,.34);
            }
            .dm-email-number-button:hover,
            .dm-email-number-button:focus-visible {
                background: rgba(91,156,255,.14);
                color: #a9c9ff;
                outline: none;
            }
            .dm-email-number-button svg {
                width: 10px;
                height: 7px;
                display: block;
                pointer-events: none;
            }
            .dm-email-native-select {
                position: absolute !important;
                width: 1px !important;
                height: 1px !important;
                opacity: 0 !important;
                pointer-events: none !important;
                overflow: hidden !important;
            }
            .dm-email-select-wrap { position: relative; width: 100%; min-width: 0; }
            .dm-email-select-button {
                position: relative;
                width: 100%;
                min-height: 38px;
                display: flex;
                align-items: center;
                border: 1px solid rgba(91,156,255,.52);
                border-radius: 7px;
                background: #0d151d;
                color: #d7e0e8;
                padding: 8px 34px 8px 10px;
                font-size: 12px;
                text-align: left;
                cursor: pointer;
                outline: none;
                box-sizing: border-box;
                transition: border-color .14s ease, background .14s ease, border-radius .14s ease;
            }
            .dm-email-select-button::after {
                content: "";
                position: absolute;
                right: 14px;
                top: 50%;
                width: 6px;
                height: 6px;
                border-right: 1.5px solid #7fb2ff;
                border-bottom: 1.5px solid #7fb2ff;
                transform: translateY(-25%) rotate(225deg);
                transition: transform .14s ease;
            }
            .dm-email-select-wrap.open .dm-email-select-button {
                border-color: rgba(91,156,255,.72);
                border-top-color: transparent;
                border-radius: 0 0 7px 7px;
                background: #0d151d;
            }
            .dm-email-select-wrap.open .dm-email-select-button::after {
                transform: translateY(-65%) rotate(45deg);
            }
            .dm-email-select-button:focus,
            .dm-email-select-button:focus-visible {
                border-color: rgba(91,156,255,.72);
                box-shadow: 0 0 0 1px rgba(91,156,255,.14);
            }
            .dm-email-select-menu {
                display: none;
                position: absolute;
                z-index: 80;
                left: 0;
                right: 0;
                bottom: calc(100% - 1px);
                max-height: 184px;
                overflow-y: auto;
                overflow-x: hidden;
                border: 1px solid rgba(91,156,255,.72);
                border-bottom: 1px solid rgba(91,156,255,.52);
                border-radius: 7px 7px 0 0;
                background: #0d151d;
                box-shadow: 0 -12px 24px rgba(0,0,0,.28);
                scrollbar-width: thin;
                scrollbar-color: rgba(91,156,255,.55) rgba(14,24,34,.35);
            }
            .dm-email-select-menu::-webkit-scrollbar { width: 6px; }
            .dm-email-select-menu::-webkit-scrollbar-track { background: rgba(14,24,34,.35); }
            .dm-email-select-menu::-webkit-scrollbar-thumb { border-radius: 999px; background: rgba(91,156,255,.55); }
            #dmReportCustom .dm-email-select-menu,
            #dmTemperatureLimitCustom .dm-email-select-menu {
                max-height: none;
                overflow-y: visible;
                scrollbar-width: none;
            }
            #dmReportCustom .dm-email-select-menu::-webkit-scrollbar,
            #dmTemperatureLimitCustom .dm-email-select-menu::-webkit-scrollbar {
                display: none;
            }
            .dm-email-select-wrap.open .dm-email-select-menu { display: block; }
            .dm-email-select-wrap.open { z-index: 90; }
            .dm-email-select-option {
                width: 100%;
                min-height: 30px;
                display: flex;
                align-items: center;
                border: 0;
                border-top: 1px solid rgba(91,156,255,.42);
                background: transparent;
                color: #b8d1ff;
                padding: 7px 10px;
                font-size: 11.5px;
                text-align: left;
                cursor: pointer;
            }
            .dm-email-select-option:first-child { border-top: 0; }
            .dm-email-select-option:hover,
            .dm-email-select-option.active { background: rgba(91,156,255,.18); color: #e0edff; }
            .dm-email-events {
                margin-top: 16px; padding: 13px 14px 10px; border: 1px solid rgba(91,156,255,.52);
                border-radius: 10px; background: rgba(13,21,29,.52);
            }
            .dm-email-event-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 18px; }
            .dm-email-check { display: flex; align-items: center; gap: 9px; min-height: 30px; color: #c8d4df; font-size: 11.5px; }
            .dm-email-check input { accent-color: #5b9cff; }
            .dm-email-status { min-height: 18px; margin-top: 12px; color: #8fa2b5; font-size: 11px; }
            .dm-email-status.success { color: #65d796; }
            .dm-email-status.error { color: #ee8585; }
            .dm-email-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 14px; }
            .dm-email-action {
                min-height: 34px; padding: 0 13px; border: 1px solid rgba(91,156,255,.52); border-radius: 7px;
                background: #1b2631; color: #d7e0e8; font-size: 10.5px; font-weight: 750;
                transition: border-color .14s ease, background .14s ease;
            }
            .dm-email-action:hover:not(:disabled) { border-color: rgba(91,156,255,.72); background: rgba(45,78,112,.48); }
            .dm-email-action.primary { border-color: rgba(91,156,255,.72); background: rgba(45,78,112,.72); color: #eef5ff; }
            .dm-email-action:disabled { opacity: .5; cursor: wait; }
            @media (max-width: 640px) {
                #dmEmailOverlay { padding: 8px; }
                .dm-email-dialog { width: 100%; max-height: 96vh; }
                .dm-email-head { padding: 14px; grid-template-columns: 40px minmax(0,1fr) 36px; }
                .dm-email-body { padding: 14px; }
                .dm-email-grid, .dm-email-event-grid, .dm-email-address-row, .dm-email-preferences-row { grid-template-columns: 1fr; }
                .dm-email-actions { flex-wrap: wrap; }
                .dm-email-action { flex: 1 1 auto; }
            }
        `;
        document.head.appendChild(style);
    }

    function createButton() {
        if (document.getElementById("emailNotificationsButton")) return;
        const smartButton = document.getElementById("smartFullCheckButton");
        const settingsButton = document.getElementById("settingsButton");
        if (!smartButton || !smartButton.parentElement) return;
        const button = document.createElement("button");
        button.id = "emailNotificationsButton";
        button.type = "button";
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-controls", "dmEmailOverlay");
        button.innerHTML = `
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M4.5 6.5h15v11h-15z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"></path>
                <path d="m5.3 7.4 6.7 5 6.7-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
            <span class="dm-email-status-dot" aria-hidden="true"></span>
        `;
        button.addEventListener("click", openDialog);
        if (settingsButton && settingsButton.parentElement) {
            settingsButton.parentElement.insertBefore(button, settingsButton);
        } else {
            smartButton.insertAdjacentElement("afterend", button);
        }
        translateUi();
    }

    const REPORT_OPTIONS = [
        ["off", "reportOff"],
        ["weekly", "reportWeekly"],
        ["monthly", "reportMonthly"],
        ["3_months", "report3Months"],
        ["6_months", "report6Months"],
        ["9_months", "report9Months"],
        ["yearly", "reportYearly"]
    ];
    const TEMPERATURE_OPTIONS_C = [80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30];

    function currentTemperatureUnit() {
        return localStorage.getItem("diskMonitorTemperatureUnit") === "fahrenheit" ? "fahrenheit" : "celsius";
    }

    function temperatureOptionLabel(valueC) {
        const value = Number(valueC);
        return currentTemperatureUnit() === "fahrenheit"
            ? `${Math.round((value * 9 / 5) + 32)} °F`
            : `${value} °C`;
    }

    function reportOptionLabel(value) {
        const match = REPORT_OPTIONS.find(item => item[0] === String(value));
        return match ? text(match[1]) : String(value || "");
    }

    function selectOptionLabel(selectId, option) {
        const value = String(option.value || "");
        if (selectId === "dmEncryption") {
            if (value === "starttls") return text("starttls");
            if (value === "ssl_tls") return text("sslTls");
            if (value === "none") return text("none");
        }
        if (selectId === "dmEmailLanguage") return value === "auto" ? text("autoLanguage") : option.textContent;
        if (selectId === "dmReport") return reportOptionLabel(value);
        if (selectId === "dmTemperatureLimit") return temperatureOptionLabel(value);
        return option.textContent;
    }

    function closeCustomSelects(exceptId = "") {
        let changed = false;
        document.querySelectorAll(".dm-email-select-wrap.open").forEach(wrap => {
            if (exceptId && wrap.id === exceptId) return;
            wrap.classList.remove("open");
            const button = wrap.querySelector(".dm-email-select-button");
            if (button) button.setAttribute("aria-expanded", "false");
            changed = true;
        });
        return changed;
    }

    function syncCustomSelect(selectId) {
        const select = document.getElementById(selectId);
        const wrap = document.getElementById(selectId + "Custom");
        if (!select || !wrap) return;
        const button = wrap.querySelector(".dm-email-select-button");
        const menu = wrap.querySelector(".dm-email-select-menu");
        if (!button || !menu) return;

        menu.innerHTML = "";
        Array.from(select.options).forEach(option => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "dm-email-select-option" + (option.value === select.value ? " active" : "");
            item.setAttribute("role", "option");
            item.setAttribute("aria-selected", option.value === select.value ? "true" : "false");
            item.textContent = selectOptionLabel(selectId, option);
            item.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                select.value = option.value;
                select.dispatchEvent(new Event("change", { bubbles: true }));
                syncCustomSelect(selectId);
                closeCustomSelects();
            });
            menu.appendChild(item);
        });

        const selected = select.options[select.selectedIndex] || select.options[0];
        button.textContent = selected ? selectOptionLabel(selectId, selected) : "";
    }

    function enhanceCustomSelect(selectId) {
        const select = document.getElementById(selectId);
        if (!select || document.getElementById(selectId + "Custom")) return;
        select.classList.add("dm-email-native-select");

        const wrap = document.createElement("div");
        wrap.className = "dm-email-select-wrap";
        wrap.id = selectId + "Custom";
        wrap.innerHTML = `
            <button class="dm-email-select-button" type="button" aria-haspopup="listbox" aria-expanded="false"></button>
            <div class="dm-email-select-menu" role="listbox"></div>
        `;
        select.insertAdjacentElement("afterend", wrap);

        const button = wrap.querySelector(".dm-email-select-button");
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            const willOpen = !wrap.classList.contains("open");
            closeCustomSelects(wrap.id);
            wrap.classList.toggle("open", willOpen);
            button.setAttribute("aria-expanded", willOpen ? "true" : "false");
            if (willOpen) {
                const active = wrap.querySelector(".dm-email-select-option.active");
                if (active) active.scrollIntoView({ block: "nearest" });
            }
        });

        select.addEventListener("change", () => syncCustomSelect(selectId));
        syncCustomSelect(selectId);
    }

    function normalizeTemperatureThreshold(value) {
        const numeric = Number(value);
        if (TEMPERATURE_OPTIONS_C.includes(numeric)) return numeric;
        return TEMPERATURE_OPTIONS_C.reduce((best, candidate) => (
            Math.abs(candidate - numeric) < Math.abs(best - numeric) ? candidate : best
        ), 55);
    }

    function setupSmtpPortStepper() {
        const input = document.getElementById("dmSmtpPort");
        const up = document.getElementById("dmSmtpPortUp");
        const down = document.getElementById("dmSmtpPortDown");
        if (!input || !up || !down) return;

        const adjust = delta => {
            const min = Number(input.min || 1);
            const max = Number(input.max || 65535);
            let current = Number(input.value);
            if (!Number.isFinite(current)) current = 587;
            const next = Math.min(max, Math.max(min, Math.round(current) + delta));
            input.value = String(next);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            input.focus({ preventScroll: true });
        };

        up.addEventListener("click", event => {
            event.preventDefault();
            adjust(1);
        });
        down.addEventListener("click", event => {
            event.preventDefault();
            adjust(-1);
        });
    }

    function createOverlay() {
        if (document.getElementById("dmEmailOverlay")) return;
        const overlay = document.createElement("div");
        overlay.id = "dmEmailOverlay";
        overlay.setAttribute("aria-hidden", "true");
        overlay.innerHTML = `
            <div class="dm-email-dialog" role="dialog" aria-modal="true" aria-labelledby="dmEmailTitle">
                <div class="dm-email-head">
                    <div class="dm-email-head-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" focusable="false">
                            <path d="M4.5 6.5h15v11h-15z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"></path>
                            <path d="m5.3 7.4 6.7 5 6.7-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></path>
                        </svg>
                    </div>
                    <div><h2 class="dm-email-title" id="dmEmailTitle"></h2><p class="dm-email-intro" id="dmEmailIntro"></p></div>
                    <button class="dm-email-close" id="dmEmailClose" type="button"></button>
                </div>
                <div class="dm-email-body">
                    <div class="dm-email-enable-row"><label for="dmEmailEnabled" id="dmEmailEnabledLabel"></label><input class="dm-email-switch" id="dmEmailEnabled" type="checkbox"></div>
                    <div class="dm-email-grid">
                        <div class="dm-email-field"><label for="dmSmtpHost" id="dmSmtpHostLabel"></label><input id="dmSmtpHost" type="text" autocomplete="off" placeholder="smtp.example.com"></div>
                        <div class="dm-email-field"><label for="dmSmtpPort" id="dmSmtpPortLabel"></label><div class="dm-email-number-wrap"><input id="dmSmtpPort" type="number" min="1" max="65535" inputmode="numeric"><div class="dm-email-number-controls" aria-hidden="false"><button class="dm-email-number-button" id="dmSmtpPortUp" type="button" aria-label="SMTP Port +"><svg viewBox="0 0 12 8" aria-hidden="true"><path d="M2 6 6 2l4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg></button><button class="dm-email-number-button" id="dmSmtpPortDown" type="button" aria-label="SMTP Port −"><svg viewBox="0 0 12 8" aria-hidden="true"><path d="m2 2 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path></svg></button></div></div></div>
                        <div class="dm-email-field"><label for="dmSmtpUsername" id="dmSmtpUsernameLabel"></label><input id="dmSmtpUsername" type="text" autocomplete="username"></div>
                        <div class="dm-email-field"><label for="dmEncryption" id="dmEncryptionLabel"></label><select id="dmEncryption"><option value="starttls">STARTTLS</option><option value="ssl_tls">SSL/TLS</option><option value="none">None</option></select></div>
                        <div class="dm-email-field dm-wide"><label for="dmSmtpPassword" id="dmSmtpPasswordLabel"></label><input id="dmSmtpPassword" type="password" autocomplete="new-password"></div>
                        <div class="dm-email-address-row">
                            <div class="dm-email-field"><label for="dmSender" id="dmSenderLabel"></label><input id="dmSender" type="email" autocomplete="off"></div>
                            <div class="dm-email-field"><label for="dmRecipient" id="dmRecipientLabel"></label><input id="dmRecipient" type="email" autocomplete="off"></div>
                        </div>
                        <div class="dm-email-preferences-row">
                            <div class="dm-email-field"><label for="dmEmailLanguage" id="dmEmailLanguageLabel"></label><select id="dmEmailLanguage"><option value="auto"></option><option value="de">Deutsch</option><option value="en">English</option><option value="fr">Français</option><option value="pt">Português</option><option value="es">Español</option></select></div>
                            <div class="dm-email-field"><label for="dmReport" id="dmReportLabel"></label><select id="dmReport"><option value="off"></option><option value="weekly"></option><option value="monthly"></option><option value="3_months"></option><option value="6_months"></option><option value="9_months"></option><option value="yearly"></option></select></div>
                            <div class="dm-email-field"><label for="dmTemperatureLimit" id="dmTemperatureLimitLabel"></label><select id="dmTemperatureLimit"><option value="80">80</option><option value="75">75</option><option value="70">70</option><option value="65">65</option><option value="60">60</option><option value="55">55</option><option value="50">50</option><option value="45">45</option><option value="40">40</option><option value="35">35</option><option value="30">30</option></select></div>
                        </div>
                    </div>
                    <div class="dm-email-events">
                        <div class="dm-email-section-title" id="dmEmailEventsTitle"></div>
                        <div class="dm-email-event-grid">
                            <label class="dm-email-check"><input id="dmNotifySmartHealth" type="checkbox"><span id="dmNotifySmartHealthLabel"></span></label>
                            <label class="dm-email-check"><input id="dmNotifySmartAttributes" type="checkbox"><span id="dmNotifySmartAttributesLabel"></span></label>
                            <label class="dm-email-check"><input id="dmNotifyMissingDrive" type="checkbox"><span id="dmNotifyMissingDriveLabel"></span></label>
                            <label class="dm-email-check"><input id="dmNotifyRaid" type="checkbox"><span id="dmNotifyRaidLabel"></span></label>
                            <label class="dm-email-check"><input id="dmNotifyTemperature" type="checkbox"><span id="dmNotifyTemperatureLabel"></span></label>
                            <label class="dm-email-check"><input id="dmNotifyRecovery" type="checkbox"><span id="dmNotifyRecoveryLabel"></span></label>
                        </div>
                    </div>
                    <div class="dm-email-status" id="dmEmailStatus"></div>
                    <div class="dm-email-actions">
                        <button class="dm-email-action" id="dmEmailTest" type="button"></button>
                        <button class="dm-email-action" id="dmEmailCancel" type="button"></button>
                        <button class="dm-email-action primary" id="dmEmailSave" type="button"></button>
                    </div>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        document.getElementById("dmEmailClose").addEventListener("click", closeDialog);
        document.getElementById("dmEmailCancel").addEventListener("click", closeDialog);
        document.getElementById("dmEmailSave").addEventListener("click", () => saveSettings(false));
        document.getElementById("dmEmailTest").addEventListener("click", sendTest);
        setupSmtpPortStepper();
        enhanceCustomSelect("dmEncryption");
        enhanceCustomSelect("dmEmailLanguage");
        enhanceCustomSelect("dmReport");
        enhanceCustomSelect("dmTemperatureLimit");
        overlay.addEventListener("click", event => {
            if (event.target === overlay) closeDialog();
            else if (!event.target.closest(".dm-email-select-wrap")) closeCustomSelects();
        });
        document.addEventListener("keydown", event => {
            if (event.key !== "Escape" || !overlay.classList.contains("visible")) return;
            if (closeCustomSelects()) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            closeDialog();
        });
        translateUi();
    }

    function translateUi() {
        const button = document.getElementById("emailNotificationsButton");
        if (button) { button.title = text("button"); button.setAttribute("aria-label", text("button")); }
        const map = {
            dmEmailTitle: "title", dmEmailIntro: "intro", dmEmailEnabledLabel: "enabled",
            dmSmtpHostLabel: "smtpServer", dmSmtpPortLabel: "smtpPort", dmEncryptionLabel: "encryption",
            dmSmtpUsernameLabel: "username", dmSmtpPasswordLabel: "password", dmSenderLabel: "sender",
            dmRecipientLabel: "recipient", dmEmailLanguageLabel: "emailLanguage", dmReportLabel: "report", dmTemperatureLimitLabel: "temperatureLimit",
            dmEmailEventsTitle: "events", dmNotifySmartHealthLabel: "smartHealth", dmNotifySmartAttributesLabel: "smartAttributes",
            dmNotifyMissingDriveLabel: "missingDrive", dmNotifyRaidLabel: "raid", dmNotifyTemperatureLabel: "temperature",
            dmNotifyRecoveryLabel: "recovery", dmEmailTest: "test", dmEmailCancel: "close", dmEmailSave: "save"
        };
        for (const [id, key] of Object.entries(map)) {
            const element = document.getElementById(id);
            if (element) element.textContent = text(key);
        }
        const closeButton = document.getElementById("dmEmailClose");
        if (closeButton) {
            closeButton.setAttribute("aria-label", text("close"));
            closeButton.title = text("close");
        }
        const auto = document.querySelector('#dmEmailLanguage option[value="auto"]');
        if (auto) auto.textContent = text("autoLanguage");
        const none = document.querySelector('#dmEncryption option[value="none"]');
        if (none) none.textContent = text("none");
        const password = document.getElementById("dmSmtpPassword");
        if (password && settings && settings.password_set) password.placeholder = text("passwordSaved");
        syncCustomSelect("dmEncryption");
        syncCustomSelect("dmEmailLanguage");
        syncCustomSelect("dmReport");
        syncCustomSelect("dmTemperatureLimit");
        updateButtonState(settings);
    }

    function setBusy(value) {
        busy = value;
        ["dmEmailTest", "dmEmailCancel", "dmEmailSave", "dmEmailClose"].forEach(id => {
            const element = document.getElementById(id);
            if (element) element.disabled = value;
        });
    }

    function status(message, kind = "") {
        const element = document.getElementById("dmEmailStatus");
        if (!element) return;
        element.textContent = message || "";
        element.className = "dm-email-status" + (kind ? ` ${kind}` : "");
    }

    function updateButtonState(value) {
        const button = document.getElementById("emailNotificationsButton");
        if (!button) return;
        button.classList.remove("dm-email-active", "dm-email-error");
        if (!value || !value.enabled) { button.title = `${text("button")} · ${text("disabled")}`; return; }
        if (value.last_error) { button.classList.add("dm-email-error"); button.title = `${text("button")} · ${text("sendFailed")}`; return; }
        button.classList.add("dm-email-active"); button.title = `${text("button")} · ${text("configured")}`;
    }

    function applySettings(value) {
        settings = value;
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ""; };
        const check = (id, v) => { const el = document.getElementById(id); if (el) el.checked = Boolean(v); };
        check("dmEmailEnabled", value.enabled);
        set("dmSmtpHost", value.smtp_host);
        set("dmSmtpPort", value.smtp_port || 587);
        set("dmEncryption", value.encryption || "starttls");
        set("dmSmtpUsername", value.username);
        set("dmSmtpPassword", "");
        set("dmSender", value.sender);
        set("dmRecipient", value.recipient);
        set("dmEmailLanguage", value.language || "auto");
        set("dmReport", value.report_interval || "off");
        set("dmTemperatureLimit", normalizeTemperatureThreshold(value.temperature_threshold_c || 55));
        check("dmNotifySmartHealth", value.notify_smart_health);
        check("dmNotifySmartAttributes", value.notify_smart_attributes);
        check("dmNotifyMissingDrive", value.notify_missing_drive);
        check("dmNotifyRaid", value.notify_raid);
        check("dmNotifyTemperature", value.notify_temperature);
        check("dmNotifyRecovery", value.notify_recovery);
        const password = document.getElementById("dmSmtpPassword");
        if (password) password.placeholder = value.password_set ? text("passwordSaved") : text("noPassword");
        syncCustomSelect("dmEncryption");
        syncCustomSelect("dmEmailLanguage");
        syncCustomSelect("dmReport");
        syncCustomSelect("dmTemperatureLimit");
        updateButtonState(value);
    }

    function payload() {
        const value = id => document.getElementById(id).value;
        const checked = id => document.getElementById(id).checked;
        const data = {
            enabled: checked("dmEmailEnabled"), smtp_host: value("dmSmtpHost").trim(),
            smtp_port: Number(value("dmSmtpPort") || 587), encryption: value("dmEncryption"),
            username: value("dmSmtpUsername").trim(), sender: value("dmSender").trim(), recipient: value("dmRecipient").trim(),
            language: value("dmEmailLanguage"), temperature_unit: currentTemperatureUnit(),
            temperature_threshold_c: Number(value("dmTemperatureLimit") || 55),
            report_interval: value("dmReport"),
            notify_smart_health: checked("dmNotifySmartHealth"), notify_smart_attributes: checked("dmNotifySmartAttributes"),
            notify_missing_drive: checked("dmNotifyMissingDrive"), notify_raid: checked("dmNotifyRaid"),
            notify_temperature: checked("dmNotifyTemperature"), notify_recovery: checked("dmNotifyRecovery")
        };
        const password = value("dmSmtpPassword");
        if (password) data.password = password;
        return data;
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            ...options,
            headers: { "Content-Type": "application/json", ...(options.headers || {}) }
        });
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok) {
            const detail = data && data.detail;
            const message = typeof detail === "string" ? detail : (detail && detail.message) || text("failed");
            throw new Error(message);
        }
        return data;
    }

    async function loadSettings() {
        try {
            const value = await request("/api/email-notifications/settings");
            applySettings(value);
            return value;
        } catch (error) {
            status(error.message || text("failed"), "error");
            return null;
        }
    }

    async function saveSettings(quiet) {
        if (busy) return null;
        setBusy(true);
        if (!quiet) status("");
        try {
            const value = await request("/api/email-notifications/settings", {
                method: "POST", body: JSON.stringify(payload())
            });
            applySettings(value);
            if (!quiet) status(text("saved"), "success");
            return value;
        } catch (error) {
            status(error.message || text("failed"), "error");
            return null;
        } finally { setBusy(false); }
    }

    async function sendTest() {
        if (busy) return;
        const saved = await saveSettings(true);
        if (!saved) return;
        setBusy(true);
        status("");
        try {
            await request("/api/email-notifications/test", { method: "POST", body: "{}" });
            status(text("testSent"), "success");
            await loadSettings();
        } catch (error) {
            status(error.message || text("failed"), "error");
            await loadSettings();
        } finally { setBusy(false); }
    }

    async function syncUiLanguage() {
        const lang = language();
        try {
            await request("/api/email-notifications/ui-language", {
                method: "POST", body: JSON.stringify({
                    language: lang,
                    temperature_unit: currentTemperatureUnit()
                })
            });
        } catch (_) {}
    }

    async function openDialog() {
        const overlay = document.getElementById("dmEmailOverlay");
        if (!overlay) return;
        overlay.classList.add("visible");
        overlay.setAttribute("aria-hidden", "false");
        status(text("loading"));
        await syncUiLanguage();
        await loadSettings();
        if (document.getElementById("dmEmailStatus").textContent === text("loading")) status("");
    }

    function closeDialog() {
        if (busy) return;
        const overlay = document.getElementById("dmEmailOverlay");
        if (!overlay) return;
        closeCustomSelects();
        overlay.classList.remove("visible");
        overlay.setAttribute("aria-hidden", "true");
    }

    function initialize() {
        injectStyle();
        createButton();
        createOverlay();
        translateUi();
        setTimeout(() => { loadSettings(); syncUiLanguage(); }, 900);

        const observer = new MutationObserver(mutations => {
            if (mutations.some(item => item.attributeName === "lang")) {
                translateUi();
                syncUiLanguage();
            }
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });

        const languageSelect = document.getElementById("languageSelect");
        if (languageSelect) languageSelect.addEventListener("change", () => setTimeout(syncUiLanguage, 0));

        const temperatureUnitSelect = document.getElementById("temperatureUnitSelect");
        if (temperatureUnitSelect) {
            temperatureUnitSelect.addEventListener("change", () => {
                setTimeout(() => {
                    syncCustomSelect("dmTemperatureLimit");
                    syncUiLanguage();
                }, 0);
            });
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
    else initialize();
})();
