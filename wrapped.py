import pandas as pd
import requests
import os
import time
from collections import Counter
from datetime import datetime
import argparse

# ========== CONFIGURAÇÃO ==========
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "SUA_CHAVE_AQUI") 
DIARY_CSV = "diary.csv"
CACHE_CSV = "tmdb_cache.csv"
REQUEST_DELAY = 0.25  # segundos entre requisições TMDb para reduzir chance de rate-limit

# ========== FUNÇÕES TMDB ==========
def tmdb_search_movie(title, year=None):
    """Pesquisa filme no TMDb e retorna o primeiro result (id, title, year) ou None."""
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": title, "include_adult": False}
    if year:
        params["year"] = year  # Refinar busca com ano de lançamento
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("results"):
        return data["results"][0]  # dicionário com id, title, release_date, etc.
    return None

def tmdb_movie_details(movie_id):
    """Retorna detalhes do filme (genres, runtime, production_countries)."""
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": TMDB_API_KEY}
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    return r.json()

def tmdb_movie_credits(movie_id):
    """Retorna créditos do filme (para extrair diretor)."""
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits"
    params = {"api_key": TMDB_API_KEY}
    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None
    return r.json()

# ========== CACHE ==========
def load_cache(path):
    if os.path.exists(path):
        df = pd.read_csv(path)
        # Verificar se tem as colunas necessárias; se não, recriar (compatibilidade com versão anterior)
        required_cols = ["title", "year", "tmdb_id", "genre", "director", "country", "runtime"]
        if not all(col in df.columns for col in required_cols):
            print("🔄 Preparando cache de dados TMDB...")
            df = pd.DataFrame(columns=required_cols)
    else:
        df = pd.DataFrame(columns=["title", "year", "tmdb_id", "genre", "director", "country", "runtime"])
    return df

def save_cache(df_cache, path):
    df_cache.to_csv(path, index=False)

# ========== ENRIQUECIMENTO ==========
def enrich_with_tmdb(df, cache_df):
    # Transformar cache em dicionário com chave (title, year) para evitar conflitos
    cache = {(row["title"], row["year"]): row for _, row in cache_df.iterrows()}

    new_rows = []
    unique_films = df[["Name", "Year"]].drop_duplicates()
    if not unique_films.empty:
        print("🔎 Enriquecendo dados com informações do TMDB...")
    
    for _, row in unique_films.iterrows():
        title = row["Name"]
        year = row["Year"]
        key = (title, year)
        if key in cache:
            continue  # Já tem no cache
        # Buscar no TMDb (sem print específico)
        result = tmdb_search_movie(title, year)
        time.sleep(REQUEST_DELAY)
        if not result:
            new_rows.append({
                "title": title,
                "year": year,
                "tmdb_id": None,
                "genre": None,
                "director": None,
                "country": None,
                "runtime": None
            })
            continue

        movie_id = result.get("id")
        details = tmdb_movie_details(movie_id)
        time.sleep(REQUEST_DELAY)
        credits = tmdb_movie_credits(movie_id)
        time.sleep(REQUEST_DELAY)

        # Gênero: pegar todos os gêneros separados por vírgula
        genres = None
        if details and details.get("genres"):
            genres = ", ".join([g["name"] for g in details["genres"]])

        # Diretor: procurar no credits por job == 'Director' (pegar o primeiro)
        director = None
        if credits and credits.get("crew"):
            for person in credits["crew"]:
                if person.get("job") == "Director":
                    director = person.get("name")
                    break

        # País: pegar todos os países separados por vírgula
        countries = None
        if details and details.get("production_countries"):
            countries = ", ".join([pc["name"] for pc in details["production_countries"]])

        # Runtime
        runtime = details.get("runtime") if details else None

        new_rows.append({
            "title": title,
            "year": year,
            "tmdb_id": movie_id,
            "genre": genres,
            "director": director,
            "country": countries,
            "runtime": runtime
        })

    # Anexar novos rows ao cache_df
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        cache_df = pd.concat([cache_df, new_df], ignore_index=True)

    # Garantir unicidade por (title, year)
    cache_df = cache_df.drop_duplicates(subset=["title", "year"], keep="first").reset_index(drop=True)
    return cache_df

# ========== HELPERs PARA MÉTRICAS ==========
def normalize_rewatch(value):
    if pd.isna(value):
        return False
    s = str(value).strip().lower()
    return s in ("yes", "y", "true", "1", "sim", "s", "reassistido", "rewatch")

# ========== FUNÇÃO PARA INSIGHTS ==========
def generate_insights(df_year, avg_rating, year_rank, director_rank, country_rank, genre_rank, total_rewatches):
    insights = []
    
    # Insight baseado na média de notas
    if not pd.isna(avg_rating):
        if avg_rating < 3.5:
            insights.append("Crítico nato. Nada escapa às suas exigências cinematográficas.")
        elif avg_rating > 4.5:
            insights.append("Você vive um romance com o cinema — tudo te encanta um pouco.")
        else:
            insights.append("Você encontra beleza no equilíbrio: nem tudo é obra-prima, mas sempre há algo a apreciar.")
    
    # Insight baseado em anos de lançamento
    if not year_rank.empty:
        median_year = df_year["Year"].median()
        if median_year < 2000:
            insights.append("Você é um curador de clássicos, preferindo filmes antigos e atemporais.")
        elif median_year > 2015:
            insights.append("Você acompanha o cinema como quem acompanha séries — sempre na estreia.")
        else:
            insights.append("Você transita entre décadas como se fossem gêneros — seu gosto é realmente amplo.")
    
    # Insight baseado em rewatchs
    if total_rewatches > len(df_year) * 0.2:  # Mais de 20% são rewatchs
        insights.append("Você é um fã leal, reassistindo filmes favoritos com frequência.")
    
    # Insight baseado em diretor favorito
    if not director_rank.empty:
        top_director = director_rank.idxmax()
        insights.append(f"Seu cinema tem assinatura: e ela é de {top_director}")
    
    # Insight baseado em países
    if not country_rank.empty:
        top_country = country_rank.idxmax()
        if "United States" in top_country:
            insights.append("Hollywood ainda é seu porto seguro cinematográfico.")
        else:
            insights.append(f"Você é um explorador global, com afinidade por filmes de {top_country}.")
    
    # Insight baseado em gêneros (se disponível)
    if not genre_rank.empty:
        top_genre = genre_rank.idxmax()
        insights.append(f"Seu gosto tem identidade: {top_genre} lidera suas escolhas com folga.")
    
    return insights[:3]  # Limitar a 3 insights para não sobrecarregar

# ========== SCRIPT PRINCIPAL ==========
def main(year_target):
    if TMDB_API_KEY == "SUA_API_KEY_AQUI":
        print("Erro: Defina sua chave da API do TMDb em TMDB_API_KEY (variável de ambiente ou no código).")
        return

    # 1) Carregar diary
    if not os.path.exists(DIARY_CSV):
        print(f"Erro: Arquivo '{DIARY_CSV}' não encontrado no diretório.")
        return

    df = pd.read_csv(DIARY_CSV)
    # Garantir colunas mínimas
    required = {"Date", "Name", "Year", "Rating", "Rewatch"}
    if not required.issubset(set(df.columns)):
        print(f"Erro: Seu CSV precisa conter as colunas mínimas: {required}")
        return

    # Converter datas
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["WatchedYear"] = df["Date"].dt.year

    # Carregar cache
    cache_df = load_cache(CACHE_CSV)

    # Enriquecer cache com filmes faltantes
    cache_df = enrich_with_tmdb(df, cache_df)
    save_cache(cache_df, CACHE_CSV)

    # Mapear dados do cache pro dataframe principal usando (title, year)
    cache_map = cache_df.set_index(["title", "year"]).to_dict(orient="index")

    def map_cache_field(title, year, field):
        key = (title, year)
        row = cache_map.get(key)
        return row.get(field) if row else None

    df["genre"] = df.apply(lambda r: map_cache_field(r["Name"], r["Year"], "genre"), axis=1)
    df["director"] = df.apply(lambda r: map_cache_field(r["Name"], r["Year"], "director"), axis=1)
    df["country"] = df.apply(lambda r: map_cache_field(r["Name"], r["Year"], "country"), axis=1)
    df["runtime"] = df.apply(lambda r: map_cache_field(r["Name"], r["Year"], "runtime"), axis=1)

    # Normalizar rating (pode ter NaN)
    df["RatingNumeric"] = pd.to_numeric(df["Rating"], errors="coerce")

    # Normalizar Rewatch
    df["RewatchBool"] = df["Rewatch"].apply(normalize_rewatch)

    # Filtrar para o ano escolhido
    df_year = df[df["WatchedYear"] == year_target].copy()

    if df_year.empty:
        print(f"Nenhum filme assistido em {year_target}.")
        return

    # ---------------- MÉTRICAS ----------------
    # 1. Média das notas no ano
    avg_rating = df_year["RatingNumeric"].mean()

    # 2. Melhor e pior filme avaliado (por nota; se empate, listar todos)
    rated_films = df_year[df_year["RatingNumeric"].notna()]
    if not rated_films.empty:
        best_rating = rated_films["RatingNumeric"].max()
        worst_rating = rated_films["RatingNumeric"].min()
        best_films = rated_films[rated_films["RatingNumeric"] == best_rating]["Name"].unique().tolist()
        worst_films = rated_films[rated_films["RatingNumeric"] == worst_rating]["Name"].unique().tolist()
    else:
        best_rating = worst_rating = None
        best_films = worst_films = []

    # 3. Distribuição de notas (porcentagem)
    dist_counts = df_year["RatingNumeric"].value_counts(dropna=True).sort_index(ascending=False)
    dist_pct = (dist_counts / dist_counts.sum() * 100).round(1) if dist_counts.sum() > 0 else pd.Series(dtype=float)

    # 4. Quantos filmes reassistidos no ano e qual o mais reassistido
    total_rewatches = df_year["RewatchBool"].sum()
    rew_count = df_year[df_year["RewatchBool"]]["Name"].value_counts()
    most_rewatched = (rew_count.idxmax(), rew_count.max()) if not rew_count.empty else (None, 0)

    # 5. Ranking dos anos de lançamento mais vistos
    year_rank = df_year["Year"].value_counts().head(10)

    # 6. Diretor(a) mais assistido(a)
    director_rank = df_year["director"].dropna().value_counts()
    top_director = (director_rank.idxmax(), director_rank.max()) if not director_rank.empty else (None, 0)

    # 7. Países mais assistidos (contar países individuais)
    all_countries = []
    for countries in df_year["country"].dropna():
        if countries:
            all_countries.extend(countries.split(", "))
    country_rank = pd.Series(all_countries).value_counts()

    # 8. Tempo total assistindo filmes no ano (runtime em minutos -> horas)
    runtimes = pd.to_numeric(df_year["runtime"], errors="coerce").dropna()
    total_minutes = runtimes.sum()
    total_hours = round(total_minutes / 60, 1) if not pd.isna(total_minutes) else 0

    # 9. Ranking de gêneros (para insights)
    genre_rank = df_year["genre"].dropna().value_counts()

    # 10. "Você em 3 filmes" -> Score baseado em rating médio * vezes visto * (1 + 0.5 * rewatch_count)
    name_counts = df_year["Name"].value_counts()
    rewatch_counts = df_year[df_year["RewatchBool"]]["Name"].value_counts()
    scores = {}
    for name, times in name_counts.items():
        mean_rating = df_year[df_year["Name"] == name]["RatingNumeric"].mean()
        rw = int(rewatch_counts.get(name, 0))
        if pd.isna(mean_rating):
            mean_rating = 0
        score = mean_rating * times * (1 + 0.5 * rw)
        scores[name] = score
    top_3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]

    # 11. Gerar insights
    insights = generate_insights(df_year, avg_rating, year_rank, director_rank, country_rank, genre_rank, total_rewatches)

    # ---------------- PRINT (OUTPUT) ----------------
    print("\n" + "="*50)
    print(f"🎬 LETTERBOXD WRAPPED — {year_target}")
    print("="*50 + "\n")

    # Total filmes
    print(f"🎯 Filmes assistidos no ano: {len(df_year)}")

    # Média nota
    if pd.isna(avg_rating):
        print("⭐ Média das notas: (sem notas registradas)")
    else:
        print(f"⭐ Média das notas: {avg_rating:.2f}")

    # Melhor / pior
    if best_rating is None:
        print("🏆 Melhor filme: (nenhum avaliado)")
        print("🔻 Pior filme: (nenhum avaliado)")
    else:
        print(f"🏆 Melhor(es) avaliado(s): {', '.join(best_films)} — {best_rating}")
        print(f"🔻 Pior(es) avaliado(s): {', '.join(worst_films)} — {worst_rating}")

    # Distribuição
    print("\n📊 Distribuição das notas (porcentagem):")
    if dist_pct.empty:
        print("   (Nenhuma nota registrada neste ano)")
    else:
        for rating, pct in dist_pct.items():
            print(f"   {rating} estrelas: {pct}%")

    # Rewatch
    print(f"\n🔁 Filmes reassistidos no ano: {int(total_rewatches)}")
    if most_rewatched[0]:
        print(f"   🥇 Filme mais reassistido: {most_rewatched[0]} ({most_rewatched[1]} vezes)")
    else:
        print("   🥇 Filme mais reassistido: Nenhum")

    # Ranking anos de lançamento
    print("\n📆 Ranking - anos de lançamento mais assistidos:")
    if year_rank.empty:
        print("   (Sem dados de ano de lançamento)")
    else:
        for y, c in year_rank.items():
            print(f"   {int(y)}: {c} filme(s)")

    # Diretor
    if top_director[0]:
        print(f"\n🎞 Diretor(a) mais assistido(a): {top_director[0]} ({top_director[1]} filmes)")
    else:
        print("\n🎞 Diretor(a) mais assistido(a): Nenhum dado")

    # Países
    print("\n🌎 Países mais assistidos (top 5):")
    if country_rank.empty:
        print("   (Sem dados de país)")
    else:
        for country, c in country_rank.head(5).items():
            print(f"   {country}: {c} filme(s)")

    # Tempo total
    print(f"\n⏳ Tempo total assistindo: {total_minutes:.0f} minutos (~{total_hours} horas)")

    # Você em 3 filmes
    print("\n🧩 Você em 3 filmes (representativos):")
    if not top_3:
        print("   (Sem filmes suficientes para calcular)")
    else:
        for i, (name, score) in enumerate(top_3, start=1):
            times = name_counts.get(name, 0)
            print(f"   {i}. {name} — score {score:.1f} (visto {times}x)")

    # Insights
    print("\n🧠 Insights sobre seu gosto:")
    if not insights:
        print("   (Sem dados suficientes para gerar insights)")
    else:
        for insight in insights:
            print(f"   • {insight}")

    print("\n✅ Wrapped gerado!\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gere seu Letterboxd Wrapped.")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="Ano para o Wrapped (padrão: ano atual)")
    args = parser.parse_args()
    main(args.year)