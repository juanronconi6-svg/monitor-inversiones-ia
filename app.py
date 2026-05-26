import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
import xml.etree.ElementTree as ET
from fpdf import FPDF
import io
import tempfile
import os
import base64

# --- 1. CONFIGURACIÓN Y TEMA VISUAL ---
st.set_page_config(page_title="Monitor de Renta Variable", layout="wide", page_icon="📈")
st.markdown("""
<style>
    .stApp { background-color: #181a20; }
    * { font-weight: 600 !important; color: #eaecef; }
    h1, h2, h3, h4, h5, h6 { color: #ffffff !important; }
    .stMetric { background-color: #2b3139; border-radius: 8px; padding: 15px 20px; border: 1px solid #474d57; box-shadow: none; }
    .stMetric label { color: #848e9c !important; font-size: 1rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; white-space: nowrap; color: #ffffff !important; }
    [data-testid="stSidebar"] { background-color: #181a20; border-right: 1px solid #2b3139; }
    .stTextInput input { background-color: #2b3139 !important; color: #ffffff !important; border: 1px solid #474d57 !important; }
    div[data-baseweb="select"] > div { background-color: #2b3139 !important; color: #ffffff !important; border-color: #474d57 !important; }
    div[data-baseweb="select"] span { color: #ffffff !important; font-weight: 700 !important; }
    div[data-baseweb="menu"], div[data-baseweb="menu"] > div, div[data-baseweb="popover"] > div { background-color: #2b3139 !important; border: 1px solid #474d57 !important; }
    ul[role="listbox"], div[role="listbox"] { background-color: #2b3139 !important; }
    li[role="option"], li[role="option"] span { background-color: #2b3139 !important; color: #ffffff !important; }
    li[role="option"]:hover, li[role="option"][aria-selected="true"] { background-color: #474d57 !important; color: #fcd535 !important; }
    .stAlert { background-color: #2b3139 !important; border: 1px solid #474d57 !important; color: #ffffff !important; }
</style>
""", unsafe_allow_html=True)

# --- 2. FUNCIONES DE ANÁLISIS TÉCNICO ---
def calcular_rsi(datos, periodo=14):
    delta = datos.diff()
    ganancia = (delta.where(delta > 0, 0)).ewm(alpha=1/periodo, adjust=False).mean()
    perdida = (-delta.where(delta < 0, 0)).ewm(alpha=1/periodo, adjust=False).mean()
    rs = ganancia / perdida
    return 100 - (100 / (1 + rs))

def calcular_niveles_clave(df, window=10):
    ultimos_datos = df.tail(window)
    soporte = ultimos_datos['Low'].min()
    resistencia = ultimos_datos['High'].max()
    return soporte, resistencia

def obtener_texto_tendencia(precio_actual, sma20, sma50, nombre_accion):
    if pd.isna(sma20) or pd.isna(sma50):
        return f"No hay datos suficientes para determinar la tendencia de {nombre_accion}."
    nombre_limpio = nombre_accion.split(" (")[0]
    if precio_actual > sma20 and sma20 > sma50:
        return f"🟢 *{nombre_limpio}* se encuentra con *tendencia alcista*."
    elif precio_actual < sma20 and sma20 < sma50:
        return f"🔴 *{nombre_limpio}* se encuentra con *tendencia bajista*."
    else:
        return f"🟡 *{nombre_limpio}* se encuentra en una *fase lateral o de consolidación*."

def buscar_ticker_por_nombre(nombre):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={nombre}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        if 'quotes' in data and len(data['quotes']) > 0:
            for quote in data['quotes']:
                if quote.get('quoteType') in ['EQUITY', 'ETF']:
                    return quote['symbol'], quote.get('shortname', quote['symbol'])
            return data['quotes'][0]['symbol'], data['quotes'][0].get('shortname', data['quotes'][0]['symbol'])
    except Exception:
        return None, None
    return None, None

def obtener_noticia_ambito():
    url = "https://www.ambito.com/rss/economia.xml" 
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        root = ET.fromstring(res.content)
        item = root.find('.//item')
        if item is not None:
            titulo = item.find('title').text
            link = item.find('link').text
            return titulo, link
    except Exception:
        return None, None
    return None, None

def obtener_noticias_secundarias():
    feeds = [
        ("Investing.com", "https://es.investing.com/rss/news_25.rss"),
        ("El Cronista", "https://www.cronista.com/files/rss/finanzasmercados.xml"),
        ("Clarín Economía", "https://www.clarin.com/rss/economia/")
    ]
    noticias = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for fuente, url in feeds:
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                items = root.findall('.//item')
                for item in items[:2]:
                    titulo = item.find('title').text
                    link = item.find('link').text
                    noticias.append((fuente, titulo, link))
        except Exception:
            continue
    return noticias

def analizar_noticias_y_sentimiento(noticias_todas, nombre_display, ticker_info):
    sector = ticker_info.get('sector', '').lower()
    industria = ticker_info.get('industry', '').lower()
    partes_nombre = nombre_display.split()
    keywords = [partes_nombre[0].lower()]
    if len(partes_nombre) > 1: keywords.append(partes_nombre[1].lower())
    if sector: keywords.append(sector)
    if industria: keywords.append(industria)
    
    positivas = ['sube', 'alza', 'crece', 'ganancia', 'récord', 'acuerdo', 'aprobación', 'mejora', 'fuerte', 'positivo', 'avanza', 'supera', 'inteligentes', 'bate']
    negativas = ['cae', 'baja', 'pérdida', 'rojo', 'retrocede', 'despide', 'demanda', 'crisis', 'negativo', 'multa', 'desplome', 'tensión']
    
    relevantes = []
    for fuente, titulo, link in noticias_todas:
        tit_lower = titulo.lower()
        if any(key in tit_lower for key in keywords if len(key) > 3):
            score = 0
            for p in positivas:
                if p in tit_lower: score += 1
            for n in negativas:
                if n in tit_lower: score -= 1
                
            if score > 0: impacto = "Positivo"
            elif score < 0: impacto = "Negativo"
            else: impacto = "Neutral"
            relevantes.append(f"- [{impacto}] {fuente}: {titulo}")
            
    return "\n".join(relevantes) if relevantes else "No se detectaron noticias de impacto corporativo o sectorial en el radar actual."

def generar_interpretacion_tecnica(data):
    r = float(data['RSI'].iloc[-1])
    m = float(data['MACD'].iloc[-1])
    s = float(data['Signal'].iloc[-1])
    p = float(data['Close'].iloc[-1])
    s20 = float(data['SMA_20'].iloc[-1])
    s50 = float(data['SMA_50'].iloc[-1])
    up = float(data['Bollinger_Upper'].iloc[-1])
    low = float(data['Bollinger_Lower'].iloc[-1])
    
    if r > 70: rsi_t = f"sobrecompra extrema (RSI > 70)"
    elif r > 55: rsi_t = f"sesgo alcista moderado (RSI en {r:.1f})"
    elif 45 <= r <= 55: rsi_t = f"neutral (RSI en {r:.1f})"
    elif r < 30: rsi_t = f"sobreventa extrema (RSI < 30)"
    else: rsi_t = f"sesgo bajista moderado (RSI en {r:.1f})"

    macd_t = "alcista" if m > s else "bajista"
    macd_detalle = f"MACD ({m:.2f}) > Señal ({s:.2f})" if m > s else f"MACD ({m:.2f}) < Señal ({s:.2f})"
    
    if p > s20 > s50: tend = "alcista consolidada"
    elif p < s20 < s50: tend = "bajista consolidada"
    else: tend = "lateral o indecisa"
    tend_detalle = f"Precio (${p:.2f}) respecto a medias (SMA20: ${s20:.2f}, SMA50: ${s50:.2f})"

    if p > up: boll_t = f"por encima de la banda superior (${up:.2f})"
    elif p < low: boll_t = f"por debajo de la banda inferior (${low:.2f})"
    else: boll_t = f"dentro de rango normal (${low:.2f} - ${up:.2f})"

    return f"- Fuerza (RSI): {rsi_t}.\n- Momentum (MACD): {macd_t} ({macd_detalle}).\n- Tendencia: {tend}. Detalle: {tend_detalle}.\n- Volatilidad (Bollinger): Precio {boll_t}."

def generar_score_y_tabla(data):
    r = float(data['RSI'].iloc[-1])
    m = float(data['MACD'].iloc[-1])
    s = float(data['Signal'].iloc[-1])
    p = float(data['Close'].iloc[-1])
    s20 = float(data['SMA_20'].iloc[-1])
    s50 = float(data['SMA_50'].iloc[-1])
    
    std_20 = float(data['StdDev_20'].iloc[-1])
    avg_std = float(data['StdDev_20'].mean())
    
    est_tend = "Alcista" if p > s20 > s50 else ("Bajista" if p < s20 < s50 else "Neutral")
    est_mom = "Alcista" if m > s else "Bajista"
    est_rsi = "Sobrecompra" if r > 70 else ("Sobreventa" if r < 30 else "Neutral")
    est_vol = "Alta" if std_20 > avg_std else "Normal"
    est_riesgo = "Elevado" if r > 70 or r < 30 or std_20 > (avg_std * 1.5) else "Medio"

    tabla_pdf = "| INDICADOR       | ESTADO          |\n"
    tabla_pdf += "|-----------------|-----------------|\n"
    tabla_pdf += f"| Tendencia       | {str(est_tend):<15} |\n"
    tabla_pdf += f"| Momentum        | {str(est_mom):<15} |\n"
    tabla_pdf += f"| RSI             | {str(est_rsi):<15} |\n"
    tabla_pdf += f"| Volatilidad     | {str(est_vol):<15} |\n"
    tabla_pdf += f"| Riesgo          | {str(est_riesgo):<15} |"

    tabla_html = f"""
    <table style="width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 15px; text-align: left; color: #ffffff;">
        <tr style="background-color: #3b424d; border-bottom: 2px solid #fcd535;">
            <th style="padding: 8px;">Indicador</th>
            <th style="padding: 8px;">Estado</th>
        </tr>
        <tr style="border-bottom: 1px solid #474d57;">
            <td style="padding: 8px;">Tendencia</td><td style="padding: 8px;">{str(est_tend)}</td>
        </tr>
        <tr style="border-bottom: 1px solid #474d57;">
            <td style="padding: 8px;">Momentum</td><td style="padding: 8px;">{str(est_mom)}</td>
        </tr>
        <tr style="border-bottom: 1px solid #474d57;">
            <td style="padding: 8px;">RSI</td><td style="padding: 8px;">{str(est_rsi)}</td>
        </tr>
        <tr style="border-bottom: 1px solid #474d57;">
            <td style="padding: 8px;">Volatilidad</td><td style="padding: 8px;">{str(est_vol)}</td>
        </tr>
        <tr>
            <td style="padding: 8px;">Riesgo</td><td style="padding: 8px;">{str(est_riesgo)}</td>
        </tr>
    </table>
    """

    puntos = 0
    if est_tend == "Alcista": puntos += 1
    elif est_tend == "Bajista": puntos -= 1
    if est_mom == "Alcista": puntos += 1
    elif est_mom == "Bajista": puntos -= 1

    if est_riesgo == "Elevado": 
        score_txt_html = "🟠 Riesgo Elevado"
        score_txt_pdf = "Riesgo Elevado"
    elif puntos >= 2: 
        score_txt_html = "🟢 Alcista"
        score_txt_pdf = "Alcista"
    elif puntos <= -1: 
        score_txt_html = "🔴 Bajista"
        score_txt_pdf = "Bajista"
    else: 
        score_txt_html = "🟡 Moderadamente Alcista"
        score_txt_pdf = "Moderadamente Alcista"

    return tabla_pdf, tabla_html, score_txt_html, score_txt_pdf

def generar_conclusiones_avanzadas(data, tendencia, momentum, volatilidad_anual, soporte, resistencia, noticias_contexto):
    r = float(data['RSI'].iloc[-1])
    std_20 = float(data['StdDev_20'].iloc[-1])
    avg_std = float(data['StdDev_20'].mean())
    
    # 1. Cálculo del Nivel de Riesgo
    if r > 70 or r < 30 or std_20 > (avg_std * 1.5):
        riesgo = "Alto"
    elif std_20 > avg_std:
        riesgo = "Medio-Alto"
    else:
        riesgo = "Medio-Bajo"
        
    # 2. Cálculo heurístico de Confianza de la señal
    confianza = 50
    if tendencia != "lateral": confianza += 15
    if tendencia == "alcista" and momentum == "alcista": confianza += 15
    elif tendencia == "bajista" and momentum == "bajista": confianza += 15
    if 40 < r < 60: confianza -= 5
    elif r > 65 or r < 35: confianza += 10
    confianza = min(max(int(confianza), 45), 92) # Tope realista entre 45% y 92%
    
    # 3. Análisis del sentimiento macro/noticias
    if "[Positivo]" in noticias_contexto: sent = "apoyado por catalizadores sectoriales positivos"
    elif "[Negativo]" in noticias_contexto: sent = "enfrentando vientos de frente (noticias negativas)"
    else: sent = "sin catalizadores informativos claros a la vista"
        
    # 4. Redacción de Escenarios
    esc_base = f"Mantenimiento del comportamiento {tendencia}, fluctuando en el rango de ${soporte:,.2f} a ${resistencia:,.2f}."
    esc_alcista = f"Quiebre de la resistencia de ${resistencia:,.2f} validado por volumen, proyectando continuidad alcista."
    esc_bajista = f"Pérdida del soporte de ${soporte:,.2f}, habilitando un retroceso hacia niveles de consolidación inferiores."
    
    # 5. Redacción del Análisis Final Combinado
    vol_desc = "elevada" if std_20 > avg_std else "contenida"
    analisis_final = f"La acción del precio evidencia una estructura {tendencia} con un momentum de corto plazo {momentum}. "
    analisis_final += f"La volatilidad se mantiene {vol_desc} ({volatilidad_anual:.2f}% anualizada). "
    analisis_final += f"Técnicamente, la gestión operativa debe observar el soporte clave de ${soporte:,.2f} para limitar pérdidas, mientras que la superación de los ${resistencia:,.2f} "
    analisis_final += f"confirmaría fortaleza direccional. A nivel macro, esto se desarrolla en un contexto {sent}."
    
    return riesgo, f"{confianza}%", esc_base, esc_alcista, esc_bajista, analisis_final

# --- 3. INTERFAZ ---
tickers_populares = {
    "🇦🇷 Grupo Financiero Galicia (GGAL)": "GGAL.BA",
    "🇦🇷 YPF S.A. (YPFD)": "YPFD.BA",
    "🇦🇷 Pampa Energía (PAMP)": "PAMP.BA",
    "🇦🇷 Edenor (EDN)": "BCBA:EDN",
    "🇦🇷 Aluar Aluminio (ALUA)": "ALUA.BA",
    "🇺🇸 Apple (AAPL)": "AAPL",
    "🇺🇸 Tesla (TSLA)": "TSLA",
    "🇺🇸 Microsoft (MSFT)": "MSFT"
}

st.sidebar.markdown("<h3 style='color: #fcd535 !important;'>Parámetros del Activo</h3>", unsafe_allow_html=True)
modo_busqueda = st.sidebar.radio("Modo de búsqueda:", ["Populares", "Ingrese Ticker"])

ticker_seleccionado = None
if modo_busqueda == "Populares":
    accion_seleccionada = st.sidebar.selectbox("Seleccione de la lista:", list(tickers_populares.keys()))
    ticker_seleccionado = tickers_populares[accion_seleccionada]
else:
    ticker_manual = st.sidebar.text_input("Ingrese el ticker (ej: META, GOOGL):")
    st.sidebar.caption("O si no lo conoce, búsquelo por nombre:")
    nombre_empresa = st.sidebar.text_input("Ingrese el nombre de la empresa:")
    
    if ticker_manual:
        ticker_seleccionado = ticker_manual.upper()
        accion_seleccionada = ticker_seleccionado
    elif nombre_empresa:
        with st.sidebar.spinner("Buscando ticker..."):
            ticker_encontrado, nombre_encontrado = buscar_ticker_por_nombre(nombre_empresa)
            if ticker_encontrado:
                st.sidebar.success(f"Encontrado: {ticker_encontrado} - {nombre_encontrado}")
                ticker_seleccionado = ticker_encontrado
                accion_seleccionada = f"{nombre_encontrado} ({ticker_encontrado})"
            else:
                st.sidebar.error("No se encontró ningún activo con ese nombre.")

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='color: #fcd535 !important;'>Parámetros del Gráfico</h3>", unsafe_allow_html=True)

temporalidad = st.sidebar.selectbox("Temporalidad de Velas:", ["Diaria", "Semanal", "Mensual"])
mapa_periodos = {"6 Meses": "6mo", "1 Año": "1y", "2 Años": "2y", "5 Años": "5y", "Máximo": "max"}
label_periodo = st.sidebar.selectbox("Historial a cargar:", list(mapa_periodos.keys()), index=1)
periodo_carga = mapa_periodos[label_periodo]
escala = st.sidebar.selectbox("Escala Eje Y:", ["Aritmética", "Logarítmica"])
mapa_intervalos = {"Diaria": "1d", "Semanal": "1wk", "Mensual": "1mo"}
intervalo_yf = mapa_intervalos[temporalidad]

titulo_noticia, link_noticia = obtener_noticia_ambito()

if ticker_seleccionado:
    if modo_busqueda == "Populares":
        nombre_display = accion_seleccionada.split(" (")[0].replace("🇦🇷 ", "").replace("🇺🇸 ", "")
    else:
        if "(" in accion_seleccionada:
            nombre_display = accion_seleccionada.split(" (")[0]
        else:
            _, nombre_display = buscar_ticker_por_nombre(ticker_seleccionado)
            if not nombre_display:
                nombre_display = ticker_seleccionado
            accion_seleccionada = f"{nombre_display} ({ticker_seleccionado})"
            
    st.markdown(f"## Ticker: {ticker_seleccionado}")
else:
    st.title("Monitor de Renta Variable y Análisis Técnico")

if ticker_seleccionado:
    try:
        with st.spinner(f"Descargando datos para {ticker_seleccionado}..."):
            data = yf.download(ticker_seleccionado, period=periodo_carga, interval=intervalo_yf, progress=False)
            if not data.empty and len(data) >= 10:
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                data = data.dropna(subset=['Close'])

                data['SMA_20'] = data['Close'].rolling(window=20).mean()
                data['SMA_50'] = data['Close'].rolling(window=50).mean()
                data['SMA_100'] = data['Close'].rolling(window=100).mean()
                data['SMA_200'] = data['Close'].rolling(window=200).mean()
                data['RSI'] = calcular_rsi(data['Close'], 14)
                
                exp1 = data['Close'].ewm(span=12, adjust=False).mean()
                exp2 = data['Close'].ewm(span=26, adjust=False).mean()
                data['MACD'] = exp1 - exp2
                data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
                
                low_min = data['Low'].rolling(window=14).min()
                high_max = data['High'].rolling(window=14).max()
                data['Stoch'] = 100 * (data['Close'] - low_min) / (high_max - low_min)
                
                sma20_actual = float(data['SMA_20'].iloc[-1]) if not pd.isna(data['SMA_20'].iloc[-1]) else np.nan
                sma50_actual = float(data['SMA_50'].iloc[-1]) if not pd.isna(data['SMA_50'].iloc[-1]) else np.nan
                precio_actual = float(data['Close'].iloc[-1])
                precio_anterior = float(data['Close'].iloc[-2]) if len(data) > 1 else precio_actual
                variacion = ((precio_actual - precio_anterior) / precio_anterior) * 100
                soporte, resistencia = calcular_niveles_clave(data, window=10)

                tendencia_str = "alcista" if precio_actual > sma20_actual and sma20_actual > sma50_actual else "bajista" if precio_actual < sma20_actual and sma20_actual < sma50_actual else "lateral"
                max_52 = data['High'].tail(252).max() if len(data) >= 252 else data['High'].max()
                drawdown = ((precio_actual - max_52) / max_52) * 100
                volatilidad = data['Close'].pct_change().std() * np.sqrt(252) * 100
                periodo_ret = 252 if len(data) >= 252 else len(data) - 1
                retorno = ((precio_actual - data['Close'].iloc[-periodo_ret]) / data['Close'].iloc[-periodo_ret]) * 100 if periodo_ret > 0 else 0

                ticker_obj = yf.Ticker(ticker_seleccionado)
                ticker_info = ticker_obj.info

                comp_name = ticker_info.get('longName', nombre_display)
                comp_sector = ticker_info.get('sector', 'No Disponible')
                comp_industry = ticker_info.get('industry', 'No Disponible')
                comp_web = ticker_info.get('website', '#')

                st.markdown(f"""
                <div style="background-color: #2b3139; border: 1px solid #474d57; border-radius: 8px; padding: 20px; margin-bottom: 25px; margin-top: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #474d57; padding-bottom: 15px; margin-bottom: 15px;">
                        <div>
                            <span style="color: #848e9c; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">Perfil Corporativo</span>
                            <h3 style="margin: 2px 0 0 0; color: #ffffff !important; font-size: 1.5rem;">{comp_name}</h3>
                        </div>
                        <div style="text-align: right;">
                            <span style="background-color: #181a20; color: #fcd535; padding: 6px 12px; border-radius: 6px; font-size: 0.9rem; font-weight: 700; border: 1px solid #fcd535;">
                                {ticker_seleccionado}
                            </span>
                        </div>
                    </div>
                    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                        <div>
                            <span style="color: #848e9c; font-size: 0.85rem;">Sector:</span>
                            <span style="color: #ffffff; font-size: 0.85rem; margin-left: 5px;">{comp_sector}</span>
                        </div>
                        <div style="border-left: 1px solid #474d57; padding-left: 20px;">
                            <span style="color: #848e9c; font-size: 0.85rem;">Industria:</span>
                            <span style="color: #ffffff; font-size: 0.85rem; margin-left: 5px;">{comp_industry}</span>
                        </div>
                        <div style="border-left: 1px solid #474d57; padding-left: 20px;">
                            <a href="{comp_web}" target="_blank" style="color: #2962FF; font-size: 0.85rem; text-decoration: none;" onmouseover="this.style.color='#fcd535'" onmouseout="this.style.color='#2962FF'">
                                🌐 Sitio Web Oficial
                            </a>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                tab_dashboard, tab_noticias, tab_informe = st.tabs(["📊 Dashboard Interactivo", "📰 Radar de Noticias", "🤖 Informe Interpretativo IA"])
                  
                with tab_dashboard:
                    st.info(obtener_texto_tendencia(precio_actual, sma20_actual, sma50_actual, accion_seleccionada))
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Precio de Cierre", f"${precio_actual:,.2f}", f"{variacion:+.2f}%")
                    col2.metric("Nivel Resistencia (10)", f"${resistencia:,.2f}")
                    col3.metric("Nivel Soporte (10)", f"${soporte:,.2f}")
                    col4.metric("RSI Actual", f"{float(data['RSI'].iloc[-1]):.1f}")

                    metricas_mostrar = []
                    per = ticker_info.get('trailingPE')
                    if isinstance(per, (int, float)): metricas_mostrar.append(("P/E Ratio", f"{per:.2f}"))
                    
                    eps = ticker_info.get('trailingEps')
                    if isinstance(eps, (int, float)): metricas_mostrar.append(("Beneficio por Acción", f"${eps:.2f}"))
                    
                    pb = ticker_info.get('priceToBook')
                    if isinstance(pb, (int, float)): metricas_mostrar.append(("Price-to-Book", f"{pb:.2f}"))
                    
                    div_rate = ticker_info.get('dividendRate', 0)
                    etf_yield = ticker_info.get('yield')
                    if isinstance(div_rate, (int, float)) and div_rate > 0:
                        metricas_mostrar.append(("Dividend Yield", f"{(div_rate / precio_actual) * 100:.2f}%"))
                    elif isinstance(etf_yield, (int, float)):
                        metricas_mostrar.append(("Yield (Fondo)", f"{etf_yield * 100:.2f}%"))
                    
                    if len(metricas_mostrar) < 4:
                        beta = ticker_info.get('beta')
                        if isinstance(beta, (int, float)): metricas_mostrar.append(("Beta (Volatilidad)", f"{beta:.2f}"))
                    
                    if len(metricas_mostrar) < 4:
                        roe = ticker_info.get('returnOnEquity')
                        if isinstance(roe, (int, float)): metricas_mostrar.append(("ROE", f"{roe * 100:.2f}%"))
                    
                    if len(metricas_mostrar) < 4:
                        margen = ticker_info.get('profitMargins')
                        if isinstance(margen, (int, float)): metricas_mostrar.append(("Margen Neto", f"{margen * 100:.2f}%"))
                    
                    if len(metricas_mostrar) < 4:
                        activos = ticker_info.get('totalAssets')
                        if isinstance(activos, (int, float)):
                            if activos >= 1e9: act_str = f"${activos/1e9:.2f}B"
                            else: act_str = f"${activos/1e6:.2f}M"
                            metricas_mostrar.append(("Activos Totales", act_str))

                    if len(metricas_mostrar) < 4:
                        mcap = ticker_info.get('marketCap')
                        if isinstance(mcap, (int, float)):
                            if mcap >= 1e12: mcap_str = f"${mcap/1e12:.2f}T"
                            elif mcap >= 1e9: mcap_str = f"${mcap/1e9:.2f}B"
                            else: mcap_str = f"${mcap/1e6:.2f}M"
                            metricas_mostrar.append(("Cap. de Mercado", mcap_str))

                    if len(metricas_mostrar) > 0:
                        st.markdown("<h5 style='margin-top: 20px; margin-bottom: 15px; color: #fcd535 !important;'>🏢 Análisis Fundamental</h5>", unsafe_allow_html=True)
                    else:
                        st.markdown("<h5 style='margin-top: 20px; margin-bottom: 15px; color: #fcd535 !important;'>📊 Desempeño del Activo</h5>", unsafe_allow_html=True)

                    metricas_matematicas = [
                        ("Volatilidad Anual", f"{volatilidad:.2f}%"),
                        ("Retorno (1 Año)", f"{retorno:+.2f}%"),
                        ("Distancia al Máx.", f"{drawdown:.2f}%"),
                        ("Máx. 52 Semanas", f"${max_52:,.2f}")
                    ]
                    
                    for metrica in metricas_matematicas:
                        if len(metricas_mostrar) >= 4:
                            break
                        metricas_mostrar.append(metrica)

                    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
                    f_col1.metric(metricas_mostrar[0][0], metricas_mostrar[0][1])
                    f_col2.metric(metricas_mostrar[1][0], metricas_mostrar[1][1])
                    f_col3.metric(metricas_mostrar[2][0], metricas_mostrar[2][1])
                    f_col4.metric(metricas_mostrar[3][0], metricas_mostrar[3][1])

                    st.markdown("<br>", unsafe_allow_html=True)

                    fig_precio = go.Figure()
                    fig_precio.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="Precio", increasing_line_color="#26a69a", decreasing_line_color="#ef5350"))
                    fig_precio.add_trace(go.Scatter(x=data.index, y=data['SMA_20'], name="SMA 20", line=dict(color="#2962FF", width=1.5)))
                    fig_precio.add_trace(go.Scatter(x=data.index, y=data['SMA_50'], name="SMA 50", line=dict(color="#FF6D00", width=1.5)))
                    fig_precio.add_trace(go.Scatter(x=data.index, y=data['SMA_100'], name="SMA 100", line=dict(color="#FFFF00", width=1.5)))
                    fig_precio.add_trace(go.Scatter(x=data.index, y=data['SMA_200'], name="SMA 200", line=dict(color="#808080", width=1.5)))
                    fig_precio.add_hline(y=resistencia, line_dash="dot", line_color="red", line_width=2, annotation_text="Resist. (10)", annotation_font_color="white")
                    fig_precio.add_hline(y=soporte, line_dash="dot", line_color="green", line_width=2, annotation_font_color="white", annotation_text="Soporte (10)") 
                    fig_precio.update_layout(title=dict(text=f"Acción del Precio ({temporalidad})", font=dict(color="white")), height=450, plot_bgcolor='#2b3139', paper_bgcolor='#2b3139', font=dict(color='white'), yaxis_type="log" if escala == "Logarítmica" else "linear", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(color='white')))
                    st.plotly_chart(fig_precio, use_container_width=True)

                    fig_rsi = go.Figure()
                    fig_rsi.add_trace(go.Scatter(x=data.index, y=data['RSI'], name="RSI", line=dict(color="#7B1FA2", width=1.5)))
                    fig_rsi.update_layout(title=dict(text="RSI (14)", font=dict(color="white")), height=250, plot_bgcolor='#2b3139', paper_bgcolor='#2b3139', font=dict(color='white'), margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(color='white')))
                    st.plotly_chart(fig_rsi, use_container_width=True)

                    fig_macd = go.Figure()
                    fig_macd.add_trace(go.Scatter(x=data.index, y=data['MACD'], name="MACD", line=dict(color="#00E676")))
                    fig_macd.add_trace(go.Scatter(x=data.index, y=data['Signal'], name="Signal", line=dict(color="#FF1744")))
                    fig_macd.update_layout(title=dict(text="MACD", font=dict(color="white")), height=250, plot_bgcolor='#2b3139', paper_bgcolor='#2b3139', font=dict(color='white'), margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(color='white')))
                    st.plotly_chart(fig_macd, use_container_width=True)

                    fig_stoch = go.Figure()
                    fig_stoch.add_trace(go.Scatter(x=data.index, y=data['Stoch'], name="Estocástico", line=dict(color="#2979FF")))
                    fig_stoch.update_layout(title=dict(text="Oscilador Estocástico", font=dict(color="white")), height=250, plot_bgcolor='#2b3139', paper_bgcolor='#2b3139', font=dict(color='white'), margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(color='white')))
                    st.plotly_chart(fig_stoch, use_container_width=True)

                    st.markdown("<h5 style='margin-top: 40px; margin-bottom: 10px; color: #fcd535 !important;'>🌪️ Análisis de Volatilidad (Bandas de Bollinger)</h5>", unsafe_allow_html=True)
                    data['StdDev_20'] = data['Close'].rolling(window=20).std()
                    data['Bollinger_Upper'] = data['SMA_20'] + (data['StdDev_20'] * 2)
                    data['Bollinger_Lower'] = data['SMA_20'] - (data['StdDev_20'] * 2)

                    fig_boll = go.Figure()
                    fig_boll.add_trace(go.Scatter(x=data.index, y=data['Bollinger_Upper'], line=dict(color='rgba(252, 213, 53, 0.4)', width=1, dash='dot'), name='Banda Sup.', hoverinfo='skip'))
                    fig_boll.add_trace(go.Scatter(x=data.index, y=data['Bollinger_Lower'], line=dict(color='rgba(252, 213, 53, 0.4)', width=1, dash='dot'), fill='tonexty', fillcolor='rgba(252, 213, 53, 0.08)', name='Banda Inf.', hoverinfo='skip'))
                    fig_boll.add_trace(go.Scatter(x=data.index, y=data['SMA_20'], line=dict(color='#fcd535', width=1.5), name='SMA 20'))
                    fig_boll.add_trace(go.Scatter(x=data.index, y=data['Close'], line=dict(color='#00ff88', width=2), name='Precio'))
                    fig_boll.update_layout(template='plotly_dark', plot_bgcolor='#2b3139', paper_bgcolor='#2b3139', margin=dict(l=10, r=10, t=40, b=10), xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#474d57'), hovermode='x unified', height=350, legend=dict(font=dict(color='white')))
                    st.plotly_chart(fig_boll, use_container_width=True)

                with tab_noticias:
                    st.markdown("<h4 style='color: #fcd535 !important; margin-top: 10px;'>Radar del Mercado Financiero</h4>", unsafe_allow_html=True)
                    st.write("Monitoreo en tiempo real de los principales portales de economía y finanzas.")
                    
                    if titulo_noticia:
                        st.markdown(f"""
                        <div style="background-color: #2b3139; border: 1px solid #fcd535; border-radius: 8px; padding: 15px 20px; margin-bottom: 15px; display: flex; align-items: center;">
                            <span style="font-size: 2rem; margin-right: 15px;">🚨</span>
                            <div>
                                <span style="color: #fcd535 !important; font-size: 0.85rem; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">Titular Principal - Ámbito Financiero</span><br>
                                <a href="{link_noticia}" target="_blank" style="color: #ffffff; text-decoration: none; font-size: 1.15rem; font-weight: 600; transition: color 0.3s;" onmouseover="this.style.color='#fcd535'" onmouseout="this.style.color='#ffffff'">
                                    {titulo_noticia}
                                </a>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    with st.spinner("Actualizando radares de noticias secundarias..."):
                        noticias_secundarias = obtener_noticias_secundarias()

                    if noticias_secundarias:
                        st.markdown("<h6 style='color: #848e9c !important; margin-top: 20px; margin-bottom: 10px;'>Otras fuentes relevantes:</h6>", unsafe_allow_html=True)
                        col_n1, col_n2 = st.columns(2)
                        
                        for i, (fuente, titulo, link) in enumerate(noticias_secundarias[:4]):
                            col = col_n1 if i % 2 == 0 else col_n2
                            col.markdown(f"""
                            <div style="background-color: #181a20; border: 1px solid #474d57; border-radius: 6px; padding: 12px; margin-bottom: 15px; height: 105px; overflow: hidden;">
                                <span style="color: #848e9c; font-size: 0.75rem; font-weight: 700; text-transform: uppercase;">🗞️ {fuente}</span><br>
                                <a href="{link}" target="_blank" style="color: #eaecef; text-decoration: none; font-size: 0.9rem; line-height: 1.3; display: block; margin-top: 4px;" onmouseover="this.style.color='#fcd535'" onmouseout="this.style.color='#eaecef'">
                                    {titulo}
                                </a>
                            </div>
                            """, unsafe_allow_html=True)

                with tab_informe:
                    st.markdown("<h4 style='color: #fcd535;'>Generador de Informe Ejecutivo Automatizado</h4>", unsafe_allow_html=True)
                    st.write("Módulo de interpretación técnica y fundamental para la toma de decisiones.")
                    
                    st.markdown("""
                    <style>
                    div.stDownloadButton > button {
                        background-color: #2b3139 !important;
                        color: #ffffff !important;
                        border: 1px solid #474d57 !important;
                    }
                    div.stDownloadButton > button:hover, 
                    div.stDownloadButton > button:active, 
                    div.stDownloadButton > button:focus {
                        background-color: #3b424d !important;
                        color: #fcd535 !important;
                        border: 1px solid #fcd535 !important;
                    }
                    </style>
                    """, unsafe_allow_html=True)

                    if st.button("Generar Informe Analítico", type="primary"):
                        with st.spinner('Generando análisis, capturando gráficos y armando PDF...'):
                            try:
                                todas_las_noticias = obtener_noticias_secundarias()
                                if titulo_noticia:
                                    todas_las_noticias.insert(0, ("Ámbito Financiero", titulo_noticia, link_noticia))
                                
                                noticias_contexto = analizar_noticias_y_sentimiento(todas_las_noticias, nombre_display, ticker_info)
                                
                                macd_actual = float(data['MACD'].iloc[-1])
                                signal_actual = float(data['Signal'].iloc[-1])
                                estado_macd = "alcista" if macd_actual > signal_actual else "bajista"
                                rsi_actual = float(data['RSI'].iloc[-1])

                                interpretacion_tecnica = generar_interpretacion_tecnica(data)
                                tabla_pdf, tabla_html, score_final_html, score_final_pdf = generar_score_y_tabla(data)

                                if rsi_actual > 70 or rsi_actual < 30:
                                    fig_a_exportar = fig_rsi
                                    nombre_grafico = "Índice de Fuerza Relativa (RSI)"
                                    analisis_grafico_texto = f"INTERPRETACION DEL GRAFICO: La figura superior ilustra el estado de {'sobrecompra' if rsi_actual > 70 else 'sobreventa'} extremo del activo. Niveles de RSI en {rsi_actual:.1f} alertan sobre un alto grado de agotamiento direccional."
                                elif volatilidad > 40 or drawdown < -20:
                                    fig_a_exportar = fig_boll
                                    nombre_grafico = "Volatilidad (Bandas de Bollinger)"
                                    analisis_grafico_texto = f"INTERPRETACION DEL GRAFICO: La imagen expone visualmente el alto nivel de riesgo actual (Volatilidad anualizada: {volatilidad:.2f}%). La amplitud del canal denota movimientos erráticos."
                                else:
                                    fig_a_exportar = fig_precio
                                    nombre_grafico = "Acción del Precio y Medias Móviles"
                                    analisis_grafico_texto = f"INTERPRETACION DEL GRAFICO: En la captura se evidencia la dinámica actual de {tendencia_str}. La clave visual radica en el comportamiento de las velas respecto a las medias móviles."

                                ruta_imagen_grafico = None
                                try:
                                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
                                        fig_a_exportar.write_image(tmpfile.name, engine="kaleido", width=900, height=450)
                                        ruta_imagen_grafico = tmpfile.name
                                except Exception as e:
                                    st.error("⚠️ Error al capturar el gráfico. ¿Aseguraste instalar 'kaleido' en la terminal?")
                                
                                explicaciones_ratios = {
                                    "P/E Ratio": "Múltiplo que indica cuánto paga el mercado por cada dólar de ganancia generada.",
                                    "Beneficio por Acción": "Porción del beneficio neto de la empresa.",
                                    "Price-to-Book": "Relación entre el precio y su valor contable.",
                                    "Dividend Yield": "Retorno que la empresa paga anualmente a sus accionistas.",
                                    "Yield (Fondo)": "Rentabilidad anual por dividendos del fondo.",
                                    "Beta (Volatilidad)": "Medida de riesgo sistemático comparado al mercado.",
                                    "ROE": "Retorno sobre el Patrimonio.",
                                    "Margen Neto": "Porcentaje de ingresos que se convierte en beneficio.",
                                    "Activos Totales": "Valor total de los activos financieros (AUM).",
                                    "Cap. de Mercado": "Valor total de las acciones en circulación.",
                                    "Volatilidad Anual": "Desviación estándar de los retornos anualizada.",
                                    "Retorno (1 Año)": "Variación porcentual en el último año móvil.",
                                    "Distancia al Máx.": "Drawdown: Caída desde el precio máximo de 52 semanas.",
                                    "Máx. 52 Semanas": "Precio histórico más alto en el último año."
                                }

                                texto_ratios = ""
                                for titulo_metrica, valor_metrica in metricas_mostrar:
                                    explicacion = explicaciones_ratios.get(titulo_metrica, "")
                                    texto_ratios += f"- {titulo_metrica} ({valor_metrica}): {explicacion}\n\n"

                                # --- NUEVAS MÉTRICAS AVANZADAS CON INTERPRETACIÓN AUTOMÁTICA ---
                                beta_val = ticker_info.get('beta', None)
                                if isinstance(beta_val, (int, float)):
                                    if beta_val > 1.2: interp_beta = "Alta sensibilidad, amplifica los movimientos del mercado."
                                    elif beta_val < 0.8: interp_beta = "Baja sensibilidad, perfil de activo defensivo."
                                    else: interp_beta = "Sensibilidad neutral, se mueve a la par del índice de referencia."
                                    texto_ratios += f"- Beta ({beta_val:.2f}): {interp_beta}\n\n"
                                
                                max_hist = data['High'].max()
                                dist_max = ((precio_actual - max_hist) / max_hist) * 100
                                interp_max = "Cerca de zona de máximos, posible resistencia fuerte." if dist_max > -5 else "Corrección profunda desde máximos, posible oportunidad de valor." if dist_max < -20 else "Corrección moderada desde la cima."
                                texto_ratios += f"- Distancia al Máximo Histórico ({dist_max:.2f}%): {interp_max}\n\n"

                                min_52 = data['Low'].tail(252).min() if len(data) >= 252 else data['Low'].min()
                                dist_min = ((precio_actual - min_52) / min_52) * 100
                                interp_min = "Fuerte rebote consolidado desde mínimos." if dist_min > 20 else "Cotizando cerca de mínimos anuales (riesgo de debilidad o zona de ganga)."
                                texto_ratios += f"- Distancia al Mínimo Anual (+{dist_min:.2f}%): {interp_min}\n\n"

                                sma200_actual = float(data['SMA_200'].iloc[-1]) if not pd.isna(data['SMA_200'].iloc[-1]) else None
                                if sma200_actual:
                                    tend_largo = "Alcista" if precio_actual > sma200_actual else "Bajista"
                                    interp_tend = "El precio sostiene un ciclo de crecimiento macro por sobre la media de 200 ruedas." if tend_largo == "Alcista" else "El precio atraviesa un invierno técnico por debajo de la media de 200 ruedas."
                                    texto_ratios += f"- Tendencia Largo Plazo (SMA 200): {tend_largo} ({interp_tend})\n\n"

                                riesgo_imp = "Medio"
                                if volatilidad > 40 or (isinstance(beta_val, (int, float)) and beta_val > 1.2):
                                    riesgo_imp = "Alto"
                                elif volatilidad < 20 and (isinstance(beta_val, (int, float)) and beta_val < 0.8):
                                    riesgo_imp = "Bajo"
                                interp_riesgo = "Alta probabilidad de oscilaciones bruscas de capital." if riesgo_imp == "Alto" else "Oscilaciones controladas y predecibles." if riesgo_imp == "Bajo" else "Riesgo estándar de mercado."
                                texto_ratios += f"- Riesgo Implícito General: {riesgo_imp} ({interp_riesgo})\n\n"

                                # --- NUEVA LLAMADA PARA CONCLUSIONES AVANZADAS ---
                                riesgo_str, confianza_str, esc_base, esc_alc, esc_baj, analisis_final_texto = generar_conclusiones_avanzadas(
                                    data, tendencia_str, estado_macd, volatilidad, soporte, resistencia, noticias_contexto
                                )

                                # --- MOTOR DE NARRATIVA INSTITUCIONAL DINÁMICA ---
                                if variacion >= 2: intro_dinamica = f"experimentando una destacable apreciación intradiaria (+{variacion:.2f}%) y consolidando un sólido interés comprador."
                                elif variacion <= -2: intro_dinamica = f"enfrentando un severo castigo en su cotización ({variacion:.2f}%), producto de una aguda presión vendedora en el mercado."
                                elif variacion > 0: intro_dinamica = f"mostrando un sesgo levemente positivo (+{variacion:.2f}%) en una sesión de comportamiento moderado."
                                else: intro_dinamica = f"transitando un letargo operativo con sesgo marginalmente negativo ({variacion:.2f}%), a la espera de nuevos drivers."

                                if tendencia_str == "alcista": accion_precio_dinamica = f"La estructura técnica confirma un claro dominio de la demanda. El activo encuentra un sólido bastión de soporte en ${soporte:,.2f}, nivel clave que debe ser defendido celosamente para atacar y consolidar el próximo objetivo de resistencia técnica en ${resistencia:,.2f}."
                                elif tendencia_str == "bajista": accion_precio_dinamica = f"El cuadro de precios exhibe un marcado deterioro estructural. Las medias móviles están actuando como resistencia dinámica, haciendo del nivel de ${resistencia:,.2f} un techo duro de vulnerar. Es imperativo vigilar la pérdida del piso en ${soporte:,.2f} para evitar claudicaciones mayores."
                                else: accion_precio_dinamica = f"El papel atraviesa una fase de lateralización y compresión temporal de volatilidad. La definición de esta pausa estratégica dependerá puramente de la ruptura direccional: ya sea validando fortaleza por sobre ${resistencia:,.2f} o cediendo ante la base de soporte en ${soporte:,.2f}."

                                if "Alto" in riesgo_str or "Elevado" in riesgo_str: 
                                    estrategia_dinamica = f"Dado el alto régimen de riesgo e inestabilidad actual, el comité sugiere una gestión de capital conservadora. La situación técnica obliga a ajustar los stop loss por debajo de los ${soporte:,.2f} ante el peligro inminente de barridas de liquidez."
                                elif tendencia_str == "alcista" and estado_macd == "alcista": 
                                    estrategia_dinamica = f"El firme alineamiento pro-cíclico de los indicadores justifica mantener una postura asertiva sobre el activo. El escenario es óptimo para dejar correr las ganancias (Let profits run), utilizando la cota de ${soporte:,.2f} como trailing stop dinámico."
                                elif tendencia_str == "bajista": 
                                    estrategia_dinamica = f"El peso de la macro-tendencia bajista desaconseja intentar atrapar pisos operativos (bottom fishing). Se recomienda neutralidad y conservación de liquidez hasta que se evidencie un patrón institucional de reversión validado por encima de los ${resistencia:,.2f}."
                                else: 
                                    estrategia_dinamica = f"El mercado no ofrece actualmente un panorama direccional de alta convicción. Se priorizan tácticas ágiles de swing trading en rangos acotados, recomendando comprar debilidad en la zona de ${soporte:,.2f} y descargar posiciones cerca del techo de ${resistencia:,.2f}."

                                texto_parte1 = f"""INFORME EJECUTIVO INSTITUCIONAL: {nombre_display} ({ticker_seleccionado})
Fecha de Emisión: {pd.Timestamp.now().strftime("%d/%m/%Y")}

1) RESUMEN EJECUTIVO Y CONTEXTO MACRO
El activo {nombre_display} cotiza a ${precio_actual:,.2f}, {intro_dinamica}

Contexto Sectorial y Noticias Relevantes (Análisis de Sentimiento):
{noticias_contexto}

2) INTERPRETACION DE INDICADORES TECNICOS
{interpretacion_tecnica}

3) ANALISIS DE LA ACCION DEL PRECIO
{accion_precio_dinamica}

A continuacion, se adjunta la captura del {nombre_grafico} en tiempo real:
"""

                                texto_parte2_pdf = f"""
{analisis_grafico_texto}

4) ANALISIS EXPLICATIVO DE RATIOS Y METRICAS
{texto_ratios.strip()}

RESUMEN DE SCORING TECNICO:
{tabla_pdf}

Score General: {score_final_pdf}

5) CONCLUSION AVANZADA Y ESTRATEGIA OPERATIVA

Nivel de Riesgo: {riesgo_str}
Confianza de senal: {confianza_str}

- Escenario Base: {esc_base}
- Escenario Alcista: {esc_alc}
- Escenario Bajista: {esc_baj}

Dictamen Final:
{estrategia_dinamica}
"""
                                
                                texto_parte2_html = f"""
{analisis_grafico_texto}

<br><br><b>4) ANALISIS EXPLICATIVO DE RATIOS Y METRICAS</b><br>
{texto_ratios.strip().replace(chr(10), '<br>')}

<br><br><b>RESUMEN DE SCORING TECNICO:</b><br>
{tabla_html}
<br><b>Score General: {score_final_html}</b>

<br><br><div style="background-color: #3b424d; padding: 15px; border-radius: 6px; border-left: 4px solid #fcd535;">
<b>5) CONCLUSIÓN AVANZADA Y ESTRATEGIA OPERATIVA</b><br><br>
<b>Nivel de Riesgo:</b> {riesgo_str}<br>
<b>Confianza de señal:</b> {confianza_str}<br><br>
<ul style="margin-top: 5px; padding-left: 20px;">
    <li><b>Escenario Base:</b> {esc_base}</li>
    <li><b>Escenario Alcista:</b> {esc_alc}</li>
    <li><b>Escenario Bajista:</b> {esc_baj}</li>
</ul>
<br><b>Dictamen Final:</b><br>
{estrategia_dinamica}
</div>
"""

                                st.success("✅ Informe generado con éxito. Vista previa:")
                                
                                html_img = ""
                                if ruta_imagen_grafico and os.path.exists(ruta_imagen_grafico):
                                    with open(ruta_imagen_grafico, "rb") as img_file:
                                        b64_string = base64.b64encode(img_file.read()).decode()
                                        html_img = f'<br><img src="data:image/png;base64,{b64_string}" style="max-width: 100%; border-radius: 5px; margin: 15px 0;"><br>'

                                html_preview = f"""
                                <div style="background-color: #2b3139; color: #ffffff; padding: 25px; border-radius: 8px; border: 1px solid #474d57; font-family: monospace; font-size: 14px; line-height: 1.5;">
                                    {texto_parte1.strip().replace(chr(10), '<br>')}
                                    {html_img}
                                    {texto_parte2_html}
                                </div>
                                """
                                st.components.v1.html(html_preview, height=800, scrolling=True)
                                
                                # 5. Creación del Archivo PDF en Modo Claro
                                pdf = FPDF()
                                pdf.add_page()
                                pdf.set_auto_page_break(auto=True, margin=15)
                                pdf.set_font("Courier", size=10) 
                                pdf.set_text_color(0, 0, 0)
                                
                                pdf.multi_cell(0, 5, txt=texto_parte1.encode('latin-1', 'replace').decode('latin-1'))
                                
                                if ruta_imagen_grafico and os.path.exists(ruta_imagen_grafico):
                                    pdf.ln(2)
                                    pdf.image(ruta_imagen_grafico, x=10, w=190)
                                    pdf.ln(5)
                                    os.remove(ruta_imagen_grafico)
                                
                                pdf.multi_cell(0, 5, txt=texto_parte2_pdf.encode('latin-1', 'replace').decode('latin-1'))
                                
                                # SOLUCIÓN: Usamos un archivo temporal en lugar de BytesIO
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                                    ruta_pdf = tmp_pdf.name
                                
                                pdf.output(ruta_pdf)
                                
                                with open(ruta_pdf, "rb") as pdf_file:
                                    pdf_bytes = pdf_file.read()
                                
                                os.remove(ruta_pdf) # Limpiamos el servidor
                                
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.download_button(
                                    label="📄 Descargar Informe en PDF",
                                    data=pdf_bytes,
                                    file_name=f"Informe_{ticker_seleccionado}.pdf",
                                    mime="application/pdf"
                                )
                            except Exception as err:
                                st.error(f"❌ Error interno al generar el informe: {err}")

            else:
                st.warning(f"⚠️ No hay suficientes datos para {ticker_seleccionado}.")
    except Exception as e:
        st.error(f"❌ Error al procesar datos: {str(e)}")
else:
    st.info("👈 Seleccione un activo en la barra lateral.")
