# app.py

import pandas as pd
import plotly.express as px
from flask import Flask, render_template, request, redirect, url_for, session
import os
import io
import uuid         # Necesario para generar identificadores únicos de archivos
import tempfile     # Necesario para manejar rutas seguras de archivos temporales

# --- Configuración de la Aplicación ---
app = Flask(__name__)
# Configuración esencial para usar la sesión (session)
app.secret_key = 'tu_clave_secreta_aqui_para_seguridad_final' 

# Directorio base para guardar los DataFrames grandes (Pickle)
TEMP_DIR = tempfile.gettempdir()


# --- Funciones Auxiliares ---

def identificar_columnas_tareas(df):
    """Filtra y devuelve los nombres de las columnas que representan actividades o tareas (para /resultados)."""
    columnas_identificacion = ['cedula', 'nombre', 'curso']
    return [
        col for col in df.columns 
        if isinstance(col, str) and col.lower().strip() not in columnas_identificacion
    ]

def identificar_columnas_evaluaciones(df):
    """Intenta identificar columnas de subtemas (asumiendo formato 0/1) para /evaluaciones."""
    columnas_identificacion = ['cedula', 'nombre', 'curso']
    cols_a_excluir = [col for col in df.columns if isinstance(col, str) and col.lower().strip() in columnas_identificacion]
    
    subtemas = []
    
    columna_nota = None
    otras_cols = [col for col in df.columns if col not in cols_a_excluir]
    if otras_cols:
        columna_nota = otras_cols[-1]

    for col in otras_cols:
        if col != columna_nota:
            try:
                # Si es una columna numérica, la consideramos subtema
                if pd.api.types.is_numeric_dtype(df[col]):
                    subtemas.append(col)
            except:
                continue 

    return subtemas

# --- Rutas de la Aplicación ---

# 1. RUTA PRINCIPAL: SUBIDA DE ARCHIVO DE TAREAS / ACTIVIDADES

@app.route('/', methods=['GET', 'POST'])
def subir_archivo():
    """Ruta para subir el archivo Excel de Tareas y guardar los datos grandes en archivo temporal."""
    if request.method == 'POST':
        file = request.files.get('archivo_excel')
        if not file or file.filename == '':
            return redirect(request.url)

        try:
            # Procesamiento de múltiples hojas (tareas)
            xls_dict = pd.read_excel(io.BytesIO(file.read()), header=2, sheet_name=None) 
            df = pd.concat(xls_dict.values(), ignore_index=True)
            
            # Limpieza y estandarización de nombres de columnas
            df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
            df = df.rename(columns={
                c: c.capitalize() for c in df.columns if isinstance(c, str) and c.lower().strip() in ['cédula', 'nombre', 'curso']
            })

            if 'Curso' not in df.columns:
                 raise ValueError("El archivo Excel debe contener una columna llamada 'Curso'.")
            
            # **SOLUCIÓN ARCHIVOS GRANDES**: Almacenar en archivo .pkl y guardar la ruta en la sesión
            file_id = str(uuid.uuid4())
            filepath = os.path.join(TEMP_DIR, f'tareas_{file_id}.pkl')
            df.to_pickle(filepath) 
            session['tareas_filepath'] = filepath
            
            return redirect(url_for('mostrar_resultados'))

        except Exception as e:
            print(f"Error al procesar el archivo: {e}")
            return render_template('index.html', error=f"Error al procesar el archivo. Detalle: {e}")

    return render_template('index.html', error=None)

# 2. RUTA DE RESULTADOS Y ANÁLISIS DE TAREAS

@app.route('/resultados', methods=['GET', 'POST'])
def mostrar_resultados():
    """Muestra filtros, gráficos y resultados estadísticos (ANALISIS DE TAREAS/ACTIVIDADES)."""
    
    # **SOLUCIÓN ARCHIVOS GRANDES**: Cargar DF desde archivo .pkl
    if 'tareas_filepath' not in session: 
        return redirect(url_for('subir_archivo'))
    try:
        df = pd.read_pickle(session['tareas_filepath']) 
    except Exception as e:
        print(f"Error al cargar archivo de tareas temporal: {e}")
        session.pop('tareas_filepath', None) 
        return redirect(url_for('subir_archivo')) 
    
    # Preparación de listas de filtros
    if 'Curso' in df.columns:
        df['Curso'] = df['Curso'].astype(str)
        cursos_disponibles = sorted(df['Curso'].unique())
    else:
        cursos_disponibles = []
        
    tareas_disponibles = identificar_columnas_tareas(df)
    
    graficos_htmls = {} 
    indicadores_agrupados_por_tarea = {}
    estadisticas_agrupadas_por_tarea = {}

    if request.method == 'POST':
        cursos_seleccionados = request.form.getlist('cursos')
        tareas_seleccionadas = request.form.getlist('tareas')
        tipo_grafico = request.form.get('tipo_grafico')
        
        if cursos_seleccionados and tareas_seleccionadas and 'Curso' in df.columns:
            
            df_filtrado = df[df['Curso'].isin(cursos_seleccionados)].copy()
            
            df_grafico_base = df_filtrado.melt(
                id_vars=['Curso'], 
                value_vars=tareas_seleccionadas, 
                var_name='Tarea', 
                value_name='Calificacion'
            ).dropna(subset=['Calificacion']).copy()
            
            # 1. Columna de calificación sea FLOAT para promedios.
            df_grafico_base['Calificacion'] = pd.to_numeric(df_grafico_base['Calificacion'], errors='coerce')
            
            # 2. Columna auxiliar redondeada (INT) SOLAMENTE para los gráficos de conteo.
            df_grafico_base['Calificacion_Entera'] = df_grafico_base['Calificacion'].round().astype('Int64') 
            

            # CÁLCULO DE PROMEDIOS FLOAT
            promedios = df_grafico_base.groupby(['Curso', 'Tarea'])['Calificacion'].mean().reset_index()

            for tarea in tareas_seleccionadas:
                # Indicadores de promedio
                indicadores_agrupados_por_tarea[tarea] = []
                promedios_tarea = promedios[promedios['Tarea'] == tarea]
                for _, row in promedios_tarea.iterrows():
                    indicadores_agrupados_por_tarea[tarea].append({
                        'curso': row['Curso'],
                        'promedio': row['Calificacion'] 
                    })

                # Estadísticas de detalle
                estadisticas_agrupadas_por_tarea[tarea] = {}
                for curso in cursos_seleccionados:
                    if tarea in df_filtrado.columns:
                        conteo_calificaciones = df_filtrado[df_filtrado['Curso'] == curso][tarea].dropna().round().astype('Int64').value_counts().sort_index()
                        estadisticas_agrupadas_por_tarea[tarea][curso] = conteo_calificaciones.to_dict()
            
            
            # GENERACIÓN DE GRÁFICOS
            etiquetas_grafico = {'Calificacion_Entera': 'Nota (0-10)', 'Cantidad_Estudiantes': 'Nº Estudiantes', 'Curso': 'Curso'} 

            for tarea in tareas_seleccionadas:
                df_tarea = df_grafico_base[df_grafico_base['Tarea'] == tarea].copy()
                
                # Agrupacion por la columna de Calificación Entera
                df_frecuencias = df_tarea.groupby(['Calificacion_Entera', 'Curso']).size().reset_index(name='Cantidad_Estudiantes')
                
                titulo_grafico = f'{tipo_grafico.capitalize()} de Frecuencias de Calificaciones para: {tarea}'
                
                if tipo_grafico == 'barras':
                    fig = px.bar(df_frecuencias, x='Calificacion_Entera', y='Cantidad_Estudiantes', color='Curso', 
                                 barmode='group', 
                                 title=titulo_grafico,
                                 labels=etiquetas_grafico)
                else: 
                    fig = px.line(df_frecuencias, x='Calificacion_Entera', y='Cantidad_Estudiantes', color='Curso',
                                  title=titulo_grafico, markers=True,
                                  labels=etiquetas_grafico)
                
                fig.update_layout(yaxis_title="Cantidad de Estudiantes", xaxis_title="Calificación (Nota)")
                fig.update_xaxes(tick0=0, dtick=1, range=[-0.5, 10.5])
                
                graficos_htmls[tarea] = fig.to_html(full_html=False)


    return render_template('resultados.html', 
                            cursos=cursos_disponibles, 
                            tareas=tareas_disponibles,
                            graficos_htmls=graficos_htmls,
                            indicadores=indicadores_agrupados_por_tarea,
                            estadisticas=estadisticas_agrupadas_por_tarea)

# 3. RUTA DE EVALUACIONES (Formatos 0/1)

@app.route('/evaluaciones', methods=['GET', 'POST'])
def mostrar_evaluaciones():
    """Ruta para la interfaz y procesamiento de datos de Evaluaciones/Subtemas."""

    # 3.1. Manejo de Subida de Archivo (POST)
    if request.method == 'POST' and 'archivo_evaluaciones' in request.files:
        file = request.files.get('archivo_evaluaciones')
        
        if not file or file.filename == '':
            return redirect(url_for('mostrar_evaluaciones'))

        try:
            file_data = file.read()
            df = pd.read_excel(io.BytesIO(file_data), header=2) 
            
            df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
            df = df.rename(columns={
                c: c.capitalize() for c in df.columns if isinstance(c, str) and c.lower().strip() in ['cédula', 'nombre', 'curso']
            })

            if 'Curso' not in df.columns:
                 raise ValueError("El archivo Excel debe contener una columna llamada 'Curso'.")
            
            file_id = str(uuid.uuid4())
            filepath = os.path.join(TEMP_DIR, f'evaluaciones_{file_id}.pkl')
            df.to_pickle(filepath) 
            session['evaluaciones_filepath'] = filepath
            
            return redirect(url_for('mostrar_evaluaciones')) 

        except Exception as e:
            error_msg = f"Error al procesar el archivo. Asegúrate de que tenga el formato correcto (header en fila 3). Detalle: {e}"
            print(error_msg)
            return render_template('evaluaciones.html', error_general=error_msg, cursos=[], subtemas=[], graficos_htmls={}, indicadores={})

    # 3.2. Manejo de Visualización y Análisis (GET y POST de filtros)

    if 'evaluaciones_filepath' not in session:
        return render_template('evaluaciones.html', error_general=None, cursos=[], subtemas=[], graficos_htmls={}, indicadores={}, estadisticas={})

    try:
        df = pd.read_pickle(session['evaluaciones_filepath'])
    except Exception as e:
        print(f"Error al cargar archivo de evaluaciones temporal: {e}")
        session.pop('evaluaciones_filepath', None)
        return redirect(url_for('mostrar_evaluaciones'))
    
    # Preparación de filtros
    if 'Curso' in df.columns:
        df['Curso'] = df['Curso'].astype(str)
        cursos_disponibles = sorted(df['Curso'].unique())
    else:
        cursos_disponibles = []
        
    subtemas_disponibles = identificar_columnas_evaluaciones(df) 
    
    graficos_htmls = {} 
    indicadores_agrupados_por_subtema = {}
    estadisticas_agrupadas_por_subtema = {}
    error_grafico = None
    
    # 3.2.1 Procesamiento de Filtros (POST de Análisis)
    if request.method == 'POST' and 'generar_analisis' in request.form:
        cursos_seleccionados = request.form.getlist('cursos')
        subtemas_seleccionados = request.form.getlist('subtemas')
        tipo_grafico = request.form.get('tipo_grafico')
        
        if not cursos_seleccionados or not subtemas_seleccionados:
             error_grafico = "Debes seleccionar al menos un Curso y un Subtema para generar el análisis."
        else:
            df_filtrado = df[df['Curso'].isin(cursos_seleccionados)].copy()
            
            df_grafico_base = df_filtrado.melt(
                id_vars=['Curso'], 
                value_vars=subtemas_seleccionados, 
                var_name='Subtema', 
                value_name='Acierto'
            ).dropna(subset=['Acierto']) 
            
            if df_grafico_base.empty:
                error_grafico = "No hay datos de acierto válidos para los filtros seleccionados."
            else:
                # La conversión a INT es correcta aquí, ya que se asume que 'Acierto' es binario (0 o 1)
                df_grafico_base['Acierto'] = df_grafico_base['Acierto'].fillna(0).astype(int)
                
                # === CÁLCULO DE PROMEDIOS (TASA DE ACIERTO 0-1) ===
                promedios = df_grafico_base.groupby(['Curso', 'Subtema'])['Acierto'].mean().reset_index()

                for subtema in subtemas_seleccionados:
                    # Indicadores de promedio (escalado a 0-10)
                    indicadores_agrupados_por_subtema[subtema] = []
                    promedios_subtema = promedios[promedios['Subtema'] == subtema]
                    for _, row in promedios_subtema.iterrows():
                        indicadores_agrupados_por_subtema[subtema].append({
                            'curso': row['Curso'],
                            'promedio': row['Acierto'] * 10
                        })

                    # Estadísticas de detalle (Conteo de 0s y 1s)
                    estadisticas_agrupadas_por_subtema[subtema] = {}
                    for curso in cursos_seleccionados:
                        df_curso = df_filtrado[df_filtrado['Curso'] == curso]
                        if subtema in df_curso.columns:
                            conteo_acierto = df_curso[subtema].value_counts().to_dict()
                            
                            estadisticas_agrupadas_por_subtema[subtema][curso] = {
                                'Aciertos (1)': conteo_acierto.get(1, 0),
                                'Errores (0)': conteo_acierto.get(0, 0)
                            }
                
                    # === GENERACIÓN DE GRÁFICOS (Tasa de Acierto Global) ===
                    df_frecuencias = promedios.rename(columns={'Acierto': 'Tasa_Acierto_Promedio'})

                    for subtema in subtemas_seleccionados:
                        df_subtema = df_frecuencias[df_frecuencias['Subtema'] == subtema].copy()
                        
                        titulo_grafico = f'{tipo_grafico.capitalize()} de Tasa de Acierto (0-1) para: {subtema}'
                        
                        if tipo_grafico == 'barras':
                            fig = px.bar(df_subtema, x='Curso', y='Tasa_Acierto_Promedio', color='Curso', 
                                         title=titulo_grafico,
                                         labels={'Tasa_Acierto_Promedio': 'Tasa de Acierto (0-1)', 'Curso': 'Curso'})
                        else: 
                            fig = px.bar(df_subtema, x='Curso', y='Tasa_Acierto_Promedio', color='Curso',
                                         title=titulo_grafico,
                                         labels={'Tasa_Acierto_Promedio': 'Tasa de Acierto (0-1)', 'Curso': 'Curso'})
                        
                        fig.update_layout(yaxis_title="Tasa de Acierto (0-1)", xaxis_title="Curso")
                        fig.update_yaxes(range=[0, 1.0])
                        
                        graficos_htmls[subtema] = fig.to_html(full_html=False)

    
    # 3.2.2 Renderizado de la página
    context = {
        'cursos': cursos_disponibles, 
        'subtemas': subtemas_disponibles,
        'graficos_htmls': graficos_htmls,
        'indicadores': indicadores_agrupados_por_subtema,
        'estadisticas': estadisticas_agrupadas_por_subtema,
        'error_general': None,
        'error_grafico': error_grafico,
        'request_form': request.form
    }

    return render_template('evaluaciones.html', **context)


# 4. RUTAS DE LIMPIEZA Y CIERRE

@app.route('/limpiar')
def limpiar_datos():
    """Ruta para borrar los datos de Tareas y redirigir a la subida de archivos."""
    # Limpia la sesión y elimina el archivo temporal
    filepath_to_delete = session.pop('tareas_filepath', None)
    session.pop('datos_excel', None) 
    
    if filepath_to_delete and os.path.exists(filepath_to_delete):
        try:
            os.remove(filepath_to_delete)
        except Exception as e:
            print(f"Error al eliminar archivo temporal de tareas: {e}")
            
    return redirect(url_for('subir_archivo'))

@app.route('/limpiar_evaluaciones')
def limpiar_evaluaciones():
    """Ruta para borrar los datos de Evaluaciones y redirigir a la interfaz de Evaluaciones."""
    # Limpia la sesión y elimina el archivo temporal
    filepath_to_delete = session.pop('evaluaciones_filepath', None)
    session.pop('datos_evaluaciones', None) 
    
    if filepath_to_delete and os.path.exists(filepath_to_delete):
        try:
            os.remove(filepath_to_delete)
        except Exception as e:
            print(f"Error al eliminar archivo temporal de evaluaciones: {e}")
            
    return redirect(url_for('mostrar_evaluaciones'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port, debug=False)
