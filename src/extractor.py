import os
from PyPDF2 import PdfReader

class MCRExtractor:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def extract(self) -> list[str]:
        """
        Lê o PDF e extrai as páginas.
        Tenta utilizar OpenDataLoader para preservar tabelas (Markdown),
        fazendo fallback para PyPDF2.
        """
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Arquivo não encontrado: {self.file_path}")

        print(f"Iniciando a extração do documento: {self.file_path}")
        pages_content = []

        # TODO: Adicionar lógica com OpenDataLoader aqui quando a lib estiver configurada.
        # Fallback para PyPDF2
        pages_content = self._extract_with_pypdf2()
        
        return pages_content

    def _extract_with_pypdf2(self) -> list[str]:
        pages_content = []
        try:
            reader = PdfReader(self.file_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    clean_text = self._clean_text(text)
                    pages_content.append(clean_text)
            print(f"Extração concluída via PyPDF2. {len(pages_content)} páginas processadas.")
        except Exception as e:
            print(f"Erro ao extrair com PyPDF2: {e}")
        
        return pages_content

    def _clean_text(self, text: str) -> str:
        """
        Limpa texto de cabeçalhos e rodapés repetitivos, como 'Banco Central do Brasil'.
        """
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remover possíveis cabeçalhos do documento
            if "Banco Central do Brasil" in line:
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

if __name__ == "__main__":
    # Caminho do arquivo a ser lido na pasta data
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(base_dir, "data", "mcr.pdf")
    
    extractor = MCRExtractor(pdf_path)
    # Apenas para testar, irá falhar caso o mcr.pdf não exista ainda em /data
    try:
        textos = extractor.extract()
        if textos:
            print(f"Primeiros 500 caracteres da extração:\n{textos[0][:500]}")
    except Exception as e:
        print(f"Atenção no teste: {e}")
