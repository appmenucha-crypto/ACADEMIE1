"""Analyse des questionnaires importés (HTML) et des questionnaires JSON.

Permet au référent d'afficher, pour chaque formation soumise par un serviteur,
le détail de ses réponses : bonne réponse en vert, mauvaise réponse en rouge.
"""
import json
import re

from django.utils.html import strip_tags

_QUESTIONS_DECL = re.compile(r'(?:const|let|var)\s+questions\s*=\s*\[')
_STRING_START = re.compile(r'''^\s*(["'])''')


def _split_top_level(text):
    """Découpe un texte JavaScript sur les virgules de premier niveau."""
    items, buf = [], []
    depth = 0
    in_string = False
    quote = ''
    escaped = False

    for ch in text:
        if in_string:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == quote:
                in_string = False
            continue

        if ch in '"\'':
            in_string = True
            quote = ch
            buf.append(ch)
        elif ch in '[{(':
            depth += 1
            buf.append(ch)
        elif ch in ']})':
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            items.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)

    items.append(''.join(buf))
    return [item.strip() for item in items if item.strip()]


def _read_js_string(text, start):
    """Lit une chaîne JavaScript à partir de start. Retourne (valeur, index_fin)."""
    match = _STRING_START.match(text[start:])
    if not match:
        return None, start
    quote = match.group(1)
    index = start + match.end()
    chars = []
    escaped = False
    while index < len(text):
        ch = text[index]
        if escaped:
            chars.append(ch)
            escaped = False
        elif ch == '\\':
            escaped = True
            chars.append(ch)
        elif ch == quote:
            return ''.join(chars), index + 1
        else:
            chars.append(ch)
        index += 1
    return None, index


def _extract_string_field(obj, name):
    """Extrait un champ texte (chaîne JavaScript) d'un objet."""
    match = re.search(r'(?<![$\w])' + re.escape(name) + r'\s*:\s*', obj)
    if not match:
        return None
    value, _ = _read_js_string(obj, match.end())
    return value


def _extract_options(obj):
    """Extrait la liste des options d'un objet question."""
    match = re.search(r'(?<![$\w])options\s*:\s*\[', obj)
    if not match:
        return []
    start = match.end()
    depth = 1
    index = start
    in_string = False
    quote = ''
    escaped = False
    while index < len(obj) and depth > 0:
        ch = obj[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == quote:
                in_string = False
        elif ch in '"\'':
            in_string = True
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        index += 1
    body = obj[start:index - 1]

    options = []
    position = 0
    while position < len(body):
        char = body[position]
        if char in '"\'':
            value, position = _read_js_string(body, position)
            if value is None:
                break
            options.append(value)
        else:
            position += 1
    return options


def _extract_int_field(obj, name):
    match = re.search(r'(?<![$\w])' + re.escape(name) + r'\s*:\s*(-?\d+)', obj)
    return int(match.group(1)) if match else None


def parse_html_questions(html):
    """Extrait les questions d'un questionnaire HTML importé.

    Retourne une liste de dicts {'q': texte, 'options': [...], 'ans': index}.
    """
    if not html:
        return []

    declaration = _QUESTIONS_DECL.search(html)
    if not declaration:
        return []

    start = declaration.end()
    depth = 1
    index = start
    in_string = False
    quote = ''
    escaped = False
    while index < len(html) and depth > 0:
        ch = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == quote:
                in_string = False
        elif ch in '"\'':
            in_string = True
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        index += 1

    body = html[start:index - 1] if depth == 0 else html[start:]

    questions = []
    for item in _split_top_level(body):
        if not item.startswith('{'):
            continue
        question = _extract_string_field(item, 'q')
        options = _extract_options(item)
        if not question or not options:
            continue
        questions.append({
            'q': question,
            'options': options,
            'ans': _extract_int_field(item, 'ans'),
        })
    return questions


def parse_json_questions(formation):
    """Extrait les questions d'un questionnaire JSON.

    Retourne une liste de dicts {'q': texte, 'options': [...], 'ans': index}.
    """
    questionnaire = getattr(formation, 'questionnaire_json', None) or []
    if isinstance(questionnaire, str):
        try:
            questionnaire = json.loads(questionnaire)
        except ValueError:
            questionnaire = []

    questions = []
    for item in questionnaire:
        if not isinstance(item, dict):
            continue
        question = item.get('question') or item.get('q') or ''
        options = item.get('options') or []
        correct = item.get('correct', item.get('ans'))
        if isinstance(correct, str) and correct.isdigit():
            correct = int(correct)
        questions.append({
            'q': question,
            'options': options,
            'ans': correct if isinstance(correct, int) else None,
            'type': item.get('type') or ('qcm' if options else 'text'),
            'answer': item.get('answer', ''),
        })
    return questions


def build_answer_detail(formation, responses):
    """Detail des réponses d'un serviteur pour une formation.

    `responses` est le dict stocké dans ServiteurFormation.html_responses.
    Les réponses sont surlignées : bonne réponse en vert, mauvaise en rouge.
    """
    responses = responses if isinstance(responses, dict) else {}

    if getattr(formation, 'questionnaire_html', ''):
        questions = parse_html_questions(formation.questionnaire_html)
        key_format = 'q{index}'
    else:
        questions = parse_json_questions(formation)
        key_format = 'question_{index}'

    detail = []
    for index, question in enumerate(questions):
        options = question.get('options') or []
        expected = question.get('ans')
        raw = responses.get(key_format.format(index=index))
        if raw is None:
            raw = responses.get(str(index))
        is_text = not options

        chosen = None
        raw_text = ''
        if raw is not None:
            raw_text = str(raw).strip()
            try:
                chosen = int(raw_text)
            except (TypeError, ValueError):
                chosen = None
        if chosen is None and raw_text and options:
            # Réponse saisie en toutes lettres
            for position, option in enumerate(options):
                if option.strip().lower() == raw_text.lower():
                    chosen = position
                    break

        if is_text:
            expected_text = str(question.get('answer', '') or '').strip()
            correct = bool(raw_text) and expected_text.lower() == raw_text.lower()
            expected_label = expected_text
            chosen_label = raw_text
        else:
            correct = (expected is not None and chosen is not None and chosen == expected)
            expected_label = options[expected] if isinstance(expected, int) and 0 <= expected < len(options) else ''
            chosen_label = options[chosen] if isinstance(chosen, int) and 0 <= chosen < len(options) else ''

        detail.append({
            'index': index,
            'question': question.get('q', ''),
            'options': options,
            'expected': expected,
            'expected_label': expected_label,
            'chosen': chosen,
            'chosen_label': chosen_label,
            'correct': correct,
            'answered': chosen is not None or bool(raw_text),
            'is_text': is_text,
        })
    return detail


def serviteur_answers_summary(formation, responses):
    """Résumé texte des réponses d'un serviteur (pour la liste des formations)."""
    detail = build_answer_detail(formation, responses)
    answered = sum(1 for item in detail if item['answered'])
    correct = sum(1 for item in detail if item['correct'])
    return {
        'total': len(detail),
        'answered': answered,
        'correct': correct,
        'incorrect': answered - correct,
        'detail': detail,
    }


def clean_text(value):
    """Nettoie une valeur issue d'un champ libre (HTML)."""
    if not value:
        return ''
    return strip_tags(str(value)).strip()
