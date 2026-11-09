from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont


PROJECT = Path(r"G:\Meu Drive\ADVALIDADO-MEMO")
SWIPES = PROJECT / "Ads Swipe Memoria"
OUTPUT = PROJECT / "Avatares Validados"


ADS = {
    "L01": {
        "roles": [("freira_principal", [14, 31, 49, 56])],
        "profile": [
            "Papel: autoridade moral/religiosa com aparência de conselheira doméstica.",
            "Faixa percebida: mulher madura, 50+; hábito de freira e expressão acolhedora.",
            "Ângulo e enquadramento: câmera na altura dos olhos, plano médio/peito, vertical 9:16.",
            "Cenário e luz: cozinha doméstica clara; mel, canela, copo e Bíblia funcionam como provas visuais.",
            "Performance: contato direto, gestos pequenos e tom confidencial; o objeto fica em primeiro plano.",
            "Uso validado: promessa simples de receita, associação entre fé, tradição e cuidado com a memória.",
        ],
        "copy": {
            "hook": ["Objeto reconhecível antes do rosto cria compreensão sem áudio.", "A autoridade religiosa reduz aparência de anúncio e enquadra a mensagem como conselho/tradição."],
            "body": ["O ingrediente permanece visível enquanto a copy conecta problema, mecanismo e ritual.", "A Bíblia e a cozinha sustentam a tese sem depender de gráficos complexos."],
            "cta": ["A ação é indicada no próprio quadro com seta e continuidade do avatar.", "O fechamento mantém o mesmo ambiente, evitando quebra de confiança."],
            "wins": ["Congruência forte entre avatar, cenário, objetos e narrativa.", "Baixa carga visual e duração curta deixam uma única promessa fácil de lembrar."],
            "apply": ["Escolher um avatar cuja identidade já explique por que ele conhece o ritual.", "Colocar os ingredientes citados dentro do quadro desde o início."]
        },
    },
    "L02": {
        "roles": [("narradora_hook", [23, 30]), ("especialista_palco", [48, 78, 102]), ("medica_103", [122, 178, 238]), ("medico_cta", [274, 289])],
        "profile": [
            "Papel: cadeia de autoridade — narradora UGC, palco de Shark Tank, médica centenária e médico no CTA.",
            "Ângulos: selfie no carro para proximidade; palco em plano aberto; médica em plano médio doméstico; CTA frontal de jaleco.",
            "Formato: 9:16 com recortes de TV e picture-in-picture.",
            "Performance: troca de porta-voz em cada etapa da persuasão; a médica de 103 anos sustenta o maior bloco.",
            "Uso validado: curiosidade de celebridade/negócio conduz a uma autoridade extrema de longevidade.",
        ],
        "copy": {
            "hook": ["Abre em uma negociação de alto valor e usa a recusa como open loop.", "A narradora traduz o clipe televisivo e promete explicar o motivo oculto."],
            "body": ["A autoridade é transferida do programa para a médica de 103 anos.", "O corpo progride de credencial para causa raiz, ritual, benefícios cotidianos e independência."],
            "cta": ["Um novo médico repete a ação, reduzindo ambiguidade no fim de um vídeo longo.", "Urgência de remoção e promessa de vídeo gratuito convertem curiosidade em clique."],
            "wins": ["Escada de credibilidade com formatos visuais diferentes evita monotonia.", "A idade extraordinária da porta-voz funciona como demonstração viva da promessa."],
            "apply": ["Construir uma ponte explícita entre o hook de entretenimento e a autoridade do body.", "Em vídeos longos, renovar o porta-voz no CTA para recuperar atenção."]
        },
    },
    "L03": {"same_as": "L02", "roles": [("narradora_hook", [23, 30]), ("especialista_palco", [48, 78, 102]), ("medica_103", [122, 178, 238]), ("medico_cta", [274, 289])], "variant": "Mesma arquitetura e mesmos takes de L02; serve como confirmação de que o conjunto de avatares foi reutilizado sem mudar a persuasão."},
    "L04": {
        "roles": [("especialista_podcast", [12, 48, 92, 126])],
        "profile": [
            "Papel: especialista madura em entrevista/podcast.",
            "Ângulo e enquadramento: três quartos leve, plano médio fechado, microfone grande visível.",
            "Formato: take horizontal/4:5 dentro de moldura editorial preta e dourada.",
            "Cenário e luz: estúdio escuro, luz quente e aparência de conteúdo publicado por terceiro.",
            "Performance: fala assertiva, gesticulação de entrevista e olhar ligeiramente fora do eixo.",
            "Uso validado: tese contrária e lista de erros/mentiras com aparência de corte de podcast.",
        ],
        "copy": {
            "hook": ["Combina demonstração visual com uma admissão de autoridade e uma ordem direta.", "A estrutura de 'três mentiras' cria expectativa enumerada e retenção."],
            "body": ["Cada mentira remove uma crença anterior antes de apresentar o novo mecanismo.", "A copy alterna diagnóstico, explicação e consequência, mantendo progressão clara."],
            "cta": ["Cartela separada elimina distrações e concentra o clique.", "A urgência retoma a ideia de informação suprimida construída no body."],
            "wins": ["A moldura faz o anúncio parecer matéria/editorial, elevando autoridade percebida.", "O microfone e o olhar fora da câmera simulam conversa espontânea."],
            "apply": ["Usar listas numeradas quando o body precisa sustentar várias crenças quebradas.", "Manter uma manchete persistente que recorde a tese durante o take longo."]
        },
    },
    "L05": {"same_as": "L04", "roles": [("especialista_podcast", [12, 48, 92, 126])], "variant": "Mesmo avatar e copy de L04 em full-screen 9:16; a validação isola a força do take sem depender da moldura editorial."},
    "L06": {
        "roles": [("homem_hook", [4, 18, 30]), ("empreendedor_shark_tank", [42, 72]), ("medica_103", [100, 152, 208, 238]), ("homem_cta", [262, 274])],
        "profile": [
            "Papel: homem jovem provoca no hook; Shark Tank valida a revelação; médica centenária sustenta o body; homem reforça o CTA.",
            "Ângulos: selfie frontal no hook, televisão no meio e plano médio doméstico na autoridade principal.",
            "Formato: 9:16 com inserts frequentes e legenda de alto contraste.",
            "Performance: energia alta no começo, desaceleração na médica e nova aceleração no fechamento.",
            "Uso validado: ameaça/conspiração de alta intensidade ligada ao mesmo corpo de autoridade usado em L02/L03.",
        ],
        "copy": {
            "hook": ["A acusação extrema interrompe o padrão e cria uma ameaça pessoal por idade.", "Números, pandemia e previdência formam uma cadeia rápida de causa e motivo."],
            "body": ["O Shark Tank transforma a acusação em pergunta e permite migrar para a médica.", "O corpo compartilhado prova que um hook radical pode alimentar um body já validado."],
            "cta": ["A médica pede o clique e um segundo homem repete benefícios e ação.", "A repetição é funcional porque chega depois de quase cinco minutos de conteúdo."],
            "wins": ["Troca de energia entre hook e body amplia o público sem perder o corpo vencedor.", "A mesma autoridade centenária ancora uma promessa muito mais agressiva."],
            "apply": ["Testar novos hooks mantendo intacto o corpo quando o encaixe causal for explícito.", "Usar CTA duplo somente em peças longas e com mensagens complementares."]
        },
    },
    "L07": {
        "roles": [("mulher_hook", [1.5, 4.5, 5.2])],
        "profile": [
            "Papel: mulher madura funciona apenas como prova humana de abertura.",
            "Ângulo e enquadramento: plano médio frontal, câmera na altura dos olhos, cozinha doméstica.",
            "Formato: 9:16 de baixa resolução; após oito segundos, o avatar desaparece.",
            "Performance: segura o pote de mel e entrega a promessa com aparência UGC.",
            "Uso validado: humanizar o primeiro contato antes de transferir toda a retenção para tipografia cinética.",
        ],
        "copy": {
            "hook": ["Rosto, cozinha e pote criam credibilidade mínima em poucos segundos.", "A transição brusca para preto funciona como segunda quebra de padrão."],
            "body": ["Sem avatar, a copy vira o produto visual: frases curtas, contraste branco/amarelo e ritmo de leitura.", "A ausência de b-roll concentra atenção na sequência lógica da argumentação."],
            "cta": ["O CTA mantém a mesma linguagem tipográfica, evitando uma nova gramática visual.", "A direção de ação depende do texto e do ritmo, não de gesto humano."],
            "wins": ["Formato incomum e barato de produzir cria alta distinção no feed.", "O avatar cumpre só a função de confiança e não compete com o body."],
            "apply": ["Usar um avatar curto para autenticar peças predominantemente tipográficas.", "Tratar cada linha como unidade de edição e destacar apenas a palavra decisiva."]
        },
    },
    "L08": {
        "roles": [("senhora_cozinha", [8, 15, 63, 105])],
        "profile": [
            "Papel: usuária madura/peer que demonstra um ritual doméstico.",
            "Ângulo e enquadramento: plano médio frontal, câmera na altura do peito/olhos, bancada visível.",
            "Formato: 9:16 em alta resolução.",
            "Cenário e luz: cozinha quente e clara, roupa rosa suave, ingredientes organizados.",
            "Performance: conversa calma, gestos com pote e ingredientes, aparência de recomendação entre pares.",
            "Uso validado: receita de mel dirigida a mulheres maduras, apoiada por autoridade e transformação familiar.",
        ],
        "copy": {
            "hook": ["O mel aparece antes da explicação, tornando a promessa concreta.", "O avatar se parece com o público e reduz distância de autoridade."],
            "body": ["Autoridade externa entra cedo e depois devolve a história à usuária.", "O body combina mecanismo, prova social e benefício relacional/familiar."],
            "cta": ["O preparo reaparece perto do CTA para lembrar que a ação é simples.", "A urgência final acontece com ingredientes em quadro."],
            "wins": ["Avatar-peer e cenário doméstico aumentam identificação.", "B-roll de mulheres maduras mostra o resultado social, não apenas cognitivo."],
            "apply": ["Para público 50+, mostrar autonomia e relações recuperadas além do sintoma.", "Repetir o ingrediente no CTA para conectar clique a uma ação concreta."]
        },
    },
    "L09": {
        "roles": [("mulher_pote_mel", [15, 34, 73, 120])],
        "profile": [
            "Papel: mulher madura como demonstradora e testemunha do ritual.",
            "Ângulo e enquadramento: plano médio frontal, cozinha ao fundo, pote grande junto ao peito.",
            "Formato: vertical dentro de canvas 4:5/1024×1280, com laterais/crop.",
            "Performance: segura o mesmo objeto por quase toda a fala e usa gestos para apontar o CTA.",
            "Uso validado: alerta de hábitos no café da manhã seguido por mecanismo de toxina e receita de mel.",
        ],
        "copy": {
            "hook": ["Começa com arrependimento pessoal e uma condição temporal de três semanas.", "A pergunta sobre a parte mais importante abre caminho para o alerta alimentar."],
            "body": ["Proíbe dois hábitos cotidianos, quantifica o problema e nomeia uma causa invisível.", "O body progride por mecanismo, rapidez, alívio de custos e independência de medicamentos/especialistas."],
            "cta": ["Preço baixo, tempo de preparo e dois ingredientes removem objeções.", "Views, botão e pedido familiar empilham prova, direção e emoção."],
            "wins": ["O pote permanece como âncora durante uma copy longa.", "Especificidade de tempo, custo e quantidade torna a solução visualizável."],
            "apply": ["Ligar o hook a um hábito frequente que o público reconhece imediatamente.", "No CTA, responder quanto custa, quanto demora e quantos itens são necessários."]
        },
    },
    "L10": {
        "roles": [("homem_entrevista", [58.5, 102.4, 190.2, 234.1, 248.7, 263.3])],
        "profile": [
            "Papel: marido/testemunha emocional em formato de entrevista.",
            "Ângulo e enquadramento: plano médio fechado, levemente três quartos, microfone amarelo em primeiro plano.",
            "Formato: 9:16 com muitos b-rolls narrativos.",
            "Cenário e luz: interior sóbrio, luz de entrevista; o amarelo do microfone vira assinatura visual.",
            "Performance: relato vulnerável, pausado e emocional, com olhar próximo do entrevistador.",
            "Uso validado: história longa de perda e recuperação da esposa, centrada nas memórias do casal.",
        ],
        "copy": {
            "hook": ["Abre contra Big Pharma e imediatamente oferece uma receita familiar simples.", "A promessa factual é seguida por história conjugal, mudando de curiosidade para emoção."],
            "body": ["Escalada de perda: chaves, compras, nomes, casamento e reconhecimento do marido.", "Depois vêm fracasso médico, encontro de autoridade, mecanismo e linha do tempo de melhora por dias."],
            "cta": ["O vídeo é apresentado como o arquivo original recebido da autoridade.", "O fechamento retorna à pessoa amada e às memórias compartilhadas, completando o arco."],
            "wins": ["O risco emocional é maior que o sintoma e sustenta quase cinco minutos.", "A progressão dia 4/dia 10/duas semanas cria prova narrativa fácil de acompanhar."],
            "apply": ["Em testimonial longo, ordenar a transformação em marcos temporais concretos.", "Fechar o CTA com o mesmo valor emocional apresentado no começo."]
        },
    },
    "L11": {
        "roles": [("profissional_saude", [9, 28, 66, 88, 104])],
        "profile": [
            "Papel: profissional de saúde em UGC doméstico.",
            "Ângulo e enquadramento: selfie frontal na altura dos olhos; plano médio que progride para close.",
            "Formato: 720×1280; mesa e sala residencial visíveis.",
            "Roupa e autoridade: jaqueta preta com aparência de uniforme/logotipo, sem cenário clínico.",
            "Performance: mão próxima da lente, sobrancelhas expressivas e contato visual contínuo.",
            "Uso validado: promessa de Vicks, experiência clínica alegada e CTA com prazo/consulta.",
        ],
        "copy": {
            "hook": ["Percentual alto, produto conhecido e prazo de 15 segundos concentram surpresa e especificidade.", "A mãe funciona como prova pessoal antes da credencial profissional."],
            "body": ["Lista sintomas cotidianos, nega a explicação da idade e nomeia um mecanismo novo.", "Depois empilha prazo, quantidade de pacientes e taxa de casos como prova."],
            "cta": ["Prazo exato, preço futuro e acesso gratuito agora formam contraste de custo.", "O medo de esquecer os netos transforma urgência funcional em consequência emocional."],
            "wins": ["Produto familiar diminui esforço de compreensão.", "Mistura de prova pessoal e autoridade profissional amplia confiança percebida."],
            "apply": ["Apresentar o item conhecido no primeiro período e explicar o mecanismo depois.", "Usar no CTA um contraste claro entre agir agora e o custo de adiar."]
        },
    },
    "L12": {"same_as": "L11", "roles": [("profissional_saude", [9, 28, 66, 88, 104])], "variant": "Mesma copy e sequência de L11 em 1080×1920; referência preferida quando for necessária maior resolução do avatar."},
    "L13": {"same_as": "L09", "roles": [("mulher_pote_mel", [16, 39, 78, 125])], "variant": "Mesmo avatar/copy de L09 com hook de favos e cauda Learn More prolongada; melhor referência para demonstrar o ingrediente e CTA persistente."},
    "L14": {
        "same_as": "L11", "roles": [("profissional_saude", [7, 24, 54, 81, 96])],
        "variant": "O mesmo avatar de L11/L12 em edição acelerada, hook trocado e enquadramento mais agressivo. Mostra que o take-base aceita compressão sem perder a função de autoridade.",
    },
    "L15": {"same_as": "L09", "roles": [("mulher_pote_mel", [16, 39, 78, 125])], "variant": "Repetição visual de L13 em outro arquivo-fonte; confirma o mesmo avatar, enquadramento e cauda de CTA."},
    "L16": {
        "roles": [("senhora_selfie", [8, 29, 70, 99, 134])],
        "profile": [
            "Papel: usuária madura/testemunha em selfie, com microfone de lapela.",
            "Ângulo e enquadramento: câmera na altura dos olhos, plano muito fechado e zooms digitais progressivos.",
            "Formato: 1080×1920; fundo cinza, espelho redondo e planta discreta.",
            "Roupa e luz: blusa rosa-claro, luz frontal suave, aparência cuidada e doméstica.",
            "Performance: expressões faciais fortes, gestos próximos da lente e fala direta para pessoas 50+.",
            "Uso validado: correção da ordem/dosagem da receita, autonomia recuperada e CTA longo repetido.",
        ],
        "copy": {
            "hook": ["Começa com consequência extrema — casa de repouso — e chama diretamente pessoas acima de 50.", "A promessa não é apenas a receita, mas o jeito certo, explicando por que tentativas falharam."],
            "body": ["O relato progride de falha para melhora em três dias, duas semanas e retorno da independência.", "Uma chamada intermediária quebra o body antes da explicação de mecanismo."],
            "cta": ["Repete passo a passo, tempo, views, ingredientes, gratuidade e risco de remoção.", "O fechamento manda preparar a primeira xícara hoje e antecipa benefício amanhã."],
            "wins": ["O ângulo de erro de execução captura quem já tentou algo parecido.", "O avatar muito próximo e expressivo sustenta uma copy quase sem b-roll."],
            "apply": ["Criar variações para públicos que já conhecem a solução, focando ordem, quantidade ou execução.", "Transformar o clique em primeiro passo concreto e com horizonte temporal curto."]
        },
    },
}


def resolve_entry(ad_id: str) -> dict:
    entry = dict(ADS[ad_id])
    if "same_as" in entry:
        base = ADS[entry["same_as"]]
        entry["profile"] = list(base["profile"])
        entry["copy"] = {key: list(value) for key, value in base["copy"].items()}
    return entry


def find_ads() -> dict[str, Path]:
    result = {}
    for config_path in SWIPES.rglob("analise/config_dossie.json"):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        result[config["id"]] = config_path.parent.parent
    return result


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return value.lower()


def crop_avatar(frame, detector):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = () if detector.empty() else detector.detectMultiScale(
        gray, scaleFactor=1.08, minNeighbors=5, minSize=(45, 45)
    )
    height, width = frame.shape[:2]
    if len(faces):
        x, y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
        x0 = max(0, int(x - 0.9 * w))
        x1 = min(width, int(x + 1.9 * w))
        y0 = max(0, int(y - 0.55 * h))
        y1 = min(height, int(y + 4.1 * h))
    else:
        crop_w = int(width * 0.72)
        crop_h = int(height * 0.82)
        x0 = (width - crop_w) // 2
        x1 = x0 + crop_w
        y0 = max(0, int(height * 0.04))
        y1 = min(height, y0 + crop_h)
    return frame[y0:y1, x0:x1]


def contact_sheet(items: list[tuple[Path, str]], target: Path) -> None:
    thumb_w, thumb_h, label_h = 360, 480, 34
    columns = 2
    rows = (len(items) + columns - 1) // columns
    canvas = Image.new("RGB", (thumb_w * columns, (thumb_h + label_h) * rows), "#111111")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, (path, label) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h))
        cell_x = (index % columns) * thumb_w
        cell_y = (index // columns) * (thumb_h + label_h)
        x = cell_x + (thumb_w - image.width) // 2
        y = cell_y + (thumb_h - image.height) // 2
        canvas.paste(image, (x, y))
        draw.text((cell_x + 8, cell_y + thumb_h + 6), label, fill="white", font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, quality=92)


def bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def process(ad_id: str, ad_dir: Path, detector) -> dict:
    entry = resolve_entry(ad_id)
    config = json.loads((ad_dir / "analise" / "config_dossie.json").read_text(encoding="utf-8"))
    metadata = json.loads((ad_dir / "analise" / "metadata.json").read_text(encoding="utf-8"))
    video = next((ad_dir / "original").glob("*.mp4"))
    out = OUTPUT / f"{ad_id}_{slug(config['nome'])}"
    refs = out / "referencias"
    refs.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    sheet_items = []
    extracted = []
    for role, times in entry["roles"]:
        for sequence, timestamp in enumerate(times, 1):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            stem = f"{slug(role)}_{sequence:02d}_{timestamp:06.2f}s"
            full_path = refs / f"{stem}_frame.jpg"
            avatar_path = refs / f"{stem}_avatar.jpg"
            cv2.imwrite(str(full_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
            avatar = crop_avatar(frame, detector)
            cv2.imwrite(str(avatar_path), avatar, [cv2.IMWRITE_JPEG_QUALITY, 95])
            sheet_items.extend([(full_path, f"{role} · {timestamp:.1f}s · frame"), (avatar_path, f"{role} · {timestamp:.1f}s · recorte")])
            extracted.append((role, timestamp, full_path.name, avatar_path.name))
    cap.release()
    contact_sheet(sheet_items, out / "FOLHA_AVATAR.jpg")

    refs_rows = "\n".join(
        f"| {role} | {timestamp:.2f}s | [frame](referencias/{full}) | [recorte](referencias/{avatar}) |"
        for role, timestamp, full, avatar in extracted
    )
    variant = entry.get("variant")
    profile_doc = f"""# {ad_id} — {config['nome']}

## Contexto validado

- Swipe de origem: `{ad_dir}`
- Arquivo: `{metadata['arquivo_original']}`
- Formato: {metadata['resolucao']} · duração {metadata['duracao_segundos']:.2f}s
- Conceito: {config['conceito']}
{f'- Leitura da variação: {variant}' if variant else ''}

## Perfil do avatar

{bullets(entry['profile'])}

## Direção que deve ser preservada

- Respeitar a função narrativa do avatar: hook, autoridade, testemunha, ponte ou CTA.
- Manter ângulo, distância da câmera, cenário, figurino e objeto de cena coerentes com a promessa.
- Usar os recortes como referência de casting e enquadramento; usar os frames integrais para cenário e composição.
- Não interpretar uma variação de crop ou velocidade como um avatar novo quando o take-base é o mesmo.

## Referências extraídas

[Abrir folha de contato](FOLHA_AVATAR.jpg)

| Papel | Tempo | Frame integral | Recorte do avatar |
|---|---:|---|---|
{refs_rows}
"""
    (out / "PERFIL_AVATAR.md").write_text(profile_doc, encoding="utf-8")

    copy = entry["copy"]
    impacts = "\n".join(f"- “{value}”" for value in config.get("impactos_literais", []))
    copy_doc = f"""# Análise estratégica de copy — {ad_id} {config['nome']}

> Esta leitura não altera a fala. A copy literal continua em `COPY_ESTRUTURADA.md`; aqui são registradas inferências sobre a arquitetura do criativo validado.

## HOOK — por que prende

{bullets(copy['hook'])}

## BODY — como sustenta atenção e crença

{bullets(copy['body'])}

## CTA — como transforma interesse em ação

{bullets(copy['cta'])}

## O que provavelmente contribuiu para a validação

{bullets(copy['wins'])}

## Como aplicar em novos criativos

{bullets(copy['apply'])}
{f'- Ao adaptar esta variação: {variant}' if variant else ''}

## Trechos de impacto literais usados como evidência

{impacts}

## Relação entre copy e avatar

- Avatar: {config['avatar']}
- Hook visual: {config['hook_visual']}
- Corpo visual: {config['corpo_visual']}
- CTA visual: {config['cta_visual']}

## Fontes internas

- [Copy literal estruturada](COPY_ESTRUTURADA.md)
- [Dossiê visual](DOSSIÊ.md)
- [Palavras de baixa confiança](PALAVRAS_BAIXA_CONFIANCA.md)
"""
    (ad_dir / "analise" / "ANALISE_ESTRATEGICA_COPY.md").write_text(copy_doc, encoding="utf-8")
    return {"id": ad_id, "name": config["nome"], "avatar_dir": out, "ad_dir": ad_dir, "roles": [r[0] for r in entry["roles"]]}


def write_catalog(rows: list[dict]) -> None:
    lines = [
        "# Avatares Validados — Memória",
        "",
        "Cada pasta contém frames integrais, recortes do avatar e uma ficha de direção. Repetições foram mantidas por ID porque resolução, crop, velocidade e função dentro da variação também fazem parte do resultado validado.",
        "",
        "| ID | Criativo | Papéis extraídos | Perfil | Copy aprofundada |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        profile = row["avatar_dir"].relative_to(OUTPUT).as_posix() + "/PERFIL_AVATAR.md"
        copy_path = Path("../Ads Swipe Memoria") / row["ad_dir"].relative_to(SWIPES) / "analise" / "ANALISE_ESTRATEGICA_COPY.md"
        lines.append(f"| {row['id']} | {row['name']} | {', '.join(row['roles'])} | [Abrir]({profile}) | [Abrir](<{copy_path.as_posix()}>) |")
    lines.extend([
        "",
        "## Famílias de avatar/take",
        "",
        "- L02/L03/L06: médica de 103 anos e ecossistema Shark Tank; L06 troca o hook.",
        "- L04/L05: mesma especialista de podcast; muda o layout editorial/full-screen.",
        "- L09/L13/L15: mesma mulher com pote de mel; mudam crop, b-roll inicial e cauda de CTA.",
        "- L11/L12/L14: mesma profissional de saúde; L14 acelera e troca o hook.",
        "",
        "Veja também [PADROES_DE_COPY_VALIDADOS.md](PADROES_DE_COPY_VALIDADOS.md).",
    ])
    (OUTPUT / "CATALOGO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path)) if cascade_path.exists() else cv2.CascadeClassifier()
    ads = find_ads()
    missing = sorted(set(ADS) - set(ads))
    if missing:
        raise RuntimeError(f"Swipes ausentes: {', '.join(missing)}")
    rows = [process(ad_id, ads[ad_id], detector) for ad_id in sorted(ADS)]
    write_catalog(rows)
    print(f"{len(rows)} swipes: avatares e análises gerados")


if __name__ == "__main__":
    main()
