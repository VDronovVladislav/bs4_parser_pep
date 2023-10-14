import re
import logging
import requests_cache

from urllib.parse import urljoin
from bs4 import BeautifulSoup
from tqdm import tqdm

from constants import (BASE_DIR, MAIN_DOC_URL, MAIN_PEP_URL, EXPECTED_STATUS)
from configs import configure_argument_parser, configure_logging
from outputs import control_output
from utils import get_response, find_tag


STATUS_COUNT_TABLE = {
    'Active': 0,
    'Accepted': 0,
    'Deferred': 0,
    'Final': 0,
    'Provisional': 0,
    'Rejected': 0,
    'Superseded': 0,
    'Withdrawn': 0,
    'Draft': 0,
    'Total': 0
}


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'}
    )

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = section.find('a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )

    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', attrs={'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')

    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
        else:
            raise Exception('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        try:
            version = re.search(pattern, a_tag.text).group('version')
            status = re.search(pattern, a_tag.text).group('status')
        except AttributeError:
            version = a_tag.text
            status = ''
        results.append(
            (link, version, status)
        )

    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    table_tag = find_tag(soup, 'table', attrs={'class': 'docutils'})
    pdf_a4_tag = find_tag(
        table_tag, 'a', {'href': re.compile(r'.+pdf-a4\.zip$')}
    )
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename

    response = session.get(archive_url)

    with open(archive_path, 'wb') as file:
        file.write(response.content)

    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    response = get_response(session, MAIN_PEP_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_table = soup.find_all(
        'table', attrs={'class': 'pep-zero-table docutils align-default'}
    )

    for table in main_table:
        table_body = find_tag(table, 'tbody')
        sections_with_pep = table_body.find_all('tr')

        for section in sections_with_pep:
            try:
                preview_status_tag = section.find('abbr').text[1:]
            except AttributeError:
                logging.exception(f'Возникла ошибка на {section}')
            href_section = section.find(
                'a', attrs={'class': 'pep reference internal'}
            )
            pep_href = href_section['href']
            pep_link = urljoin(MAIN_PEP_URL, pep_href)
            response = get_response(session, pep_link)
            if response is None:
                continue

            soup = BeautifulSoup(response.text, features='lxml')
            main_dl = find_tag(
                soup, 'dl', attrs={'class': 'rfc2822 field-list simple'}
            )
            pre_status_section = main_dl.find(string=['Status']).parent
            status = pre_status_section.find_next_sibling().text

            if status not in EXPECTED_STATUS[preview_status_tag]:
                logging.info(f'''
                    Несовпадающие статусы: {pep_link},
                    Статус в карточке: {status},
                    Ожидаемый статус: {EXPECTED_STATUS[preview_status_tag]}
                ''')
                continue

            STATUS_COUNT_TABLE[status] += 1
            STATUS_COUNT_TABLE['Total'] += 1

    result = [('Статус', 'Количество')]
    for status, count in STATUS_COUNT_TABLE.items():
        result.append(
            (status, count)
        )
    return result


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()

    if args.clear_cache:
        session.cache.clear

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)

    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
