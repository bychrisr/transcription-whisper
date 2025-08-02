import os
import re
from pathlib import Path
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

class AudioMergeService:
    def __init__(self, input_dir: str, output_parts_dir: str, output_dir: str):
        self.input_dir = Path(input_dir)
        self.output_parts_dir = Path(output_parts_dir)
        self.output_dir = Path(output_dir)
    
    def find_audio_parts(self, base_name: str) -> List[Path]:
        """Encontrar todas as partes de um áudio"""
        pattern = re.compile(rf"{re.escape(base_name)}_part(\d+)\.txt$")
        parts = []
        
        for file_path in self.output_parts_dir.iterdir():
            if file_path.is_file():
                match = pattern.match(file_path.name)
                if match:
                    parts.append((int(match.group(1)), file_path))
        
        # Ordenar por número da parte
        parts.sort(key=lambda x: x[0])
        return [part[1] for part in parts]
    
    def can_merge_parts(self, base_name: str) -> bool:
        """Verificar se todas as partes estão presentes para merge"""
        parts = self.find_audio_parts(base_name)
        if not parts:
            return False
        
        # Verificar se há partes sequenciais sem lacunas
        part_numbers = [int(re.search(r'_part(\d+)\.txt$', part.name).group(1)) 
                       for part in parts]
        
        expected_numbers = list(range(1, len(part_numbers) + 1))
        return part_numbers == expected_numbers
    
    def merge_audio_parts(self, base_name: str) -> Optional[Path]:
        """Fazer merge das partes de áudio em um arquivo completo"""
        if not self.can_merge_parts(base_name):
            logger.info(f"Não é possível fazer merge das partes para {base_name} - partes faltando ou fora de sequência")
            return None
        
        parts = self.find_audio_parts(base_name)
        if not parts:
            return None
        
        # Criar arquivo de saída
        output_file = self.output_dir / f"{base_name}.txt"
        
        try:
            with open(output_file, 'w', encoding='utf-8') as outfile:
                for i, part_file in enumerate(parts):
                    if i > 0:  # Adicionar nova linha entre partes
                        outfile.write("\n\n")
                    
                    with open(part_file, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
            
            # Remover partes após merge
            for part_file in parts:
                try:
                    part_file.unlink()
                    logger.info(f"Parte removida após merge: {part_file}")
                except Exception as e:
                    logger.warning(f"Não foi possível remover parte {part_file}: {e}")
            
            logger.info(f"Merge concluído: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Erro ao fazer merge das partes para {base_name}: {e}")
            return None
    
    def cleanup_original_audio_parts(self, base_name: str, source_dir: Path):
        """Remover arquivos de áudio originais após processamento"""
        pattern = re.compile(rf"{re.escape(base_name)}_part\d+\.")
        
        for file_path in source_dir.iterdir():
            if file_path.is_file() and pattern.match(file_path.name):
                try:
                    file_path.unlink()
                    logger.info(f"Áudio original removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Não foi possível remover áudio original {file_path}: {e}")