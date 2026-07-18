import io
from datetime import date

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

from apps.site.models import (
    CategoriaQuarto,
    ConfiguracaoSite,
    Depoimento,
    Experiencia,
    FotoGaleria,
    FotoQuarto,
    Hospede,
    Quarto,
    Temporada,
)


def gerar_imagem(largura, altura, texto, cor_fundo, cor_texto='#EFDBB2'):
    """Gera uma imagem placeholder com texto centralizado."""
    img = Image.new('RGB', (largura, altura), cor_fundo)
    draw = ImageDraw.Draw(img)

    # Tentar usar fonte do sistema, senão usa default
    tamanho_fonte = min(largura, altura) // 12
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', tamanho_fonte)
    except OSError:
        font = ImageFont.load_default()

    # Texto centralizado
    bbox = draw.textbbox((0, 0), texto, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (largura - tw) // 2
    y = (altura - th) // 2
    draw.text((x, y), texto, fill=cor_texto, font=font)

    # Borda decorativa
    draw.rectangle([10, 10, largura - 10, altura - 10], outline=cor_texto, width=2)

    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    buffer.seek(0)
    return buffer


# Paleta da pousada
NOTURNO = '#051C2C'
MADEIRA = '#4F2C1D'
LAMPIAO = '#D7A048'
MUSGO = '#2E483E'


class Command(BaseCommand):
    help = 'Popula o banco com dados fictícios e imagens placeholder'

    def handle(self, *args, **options):
        self.stdout.write('Populando dados fictícios...\n')

        # ==========================================
        # CATEGORIAS DE QUARTOS
        # ==========================================
        categorias_data = [
            {'nome': 'Suíte Premium', 'descricao': 'Quartos de luxo com vista privilegiada', 'ordem': 1},
            {'nome': 'Suíte Temática', 'descricao': 'Quartos com decoração steampunk única', 'ordem': 2},
            {'nome': 'Chalé Família', 'descricao': 'Espaços amplos para famílias', 'ordem': 3},
            {'nome': 'Standard', 'descricao': 'Conforto essencial com charme', 'ordem': 4},
        ]
        categorias = {}
        for c in categorias_data:
            obj, _ = CategoriaQuarto.objects.get_or_create(nome=c['nome'], defaults=c)
            categorias[c['nome']] = obj
        self.stdout.write(f'  Categorias: {len(categorias)}')

        # ==========================================
        # QUARTOS
        # ==========================================
        quartos_data = [
            {
                'nome': 'Cabine do Navegador',
                'categoria': categorias['Suíte Premium'],
                'descricao': 'A Cabine do Navegador é uma suíte premium que transporta você para uma viagem marítima steampunk. Com vista panorâmica para o lago, banheira de cobre envelhecido e decoração náutica repleta de mapas antigos, bússolas e instrumentos de navegação. O piso de madeira de demolição e as luminárias em estilo industrial completam a atmosfera.',
                'descricao_curta': 'Vista para o lago, banheira de cobre e decoração náutica steampunk.',
                'capacidade': 2, 'metragem': 35, 'preco_base': 480,
                'status': 'disponivel', 'destaque': True, 'nota_avaliacao': 4.9, 'ordem': 1,
                'cor': NOTURNO,
            },
            {
                'nome': 'Oficina do Relojoeiro',
                'categoria': categorias['Suíte Temática'],
                'descricao': 'A Oficina do Relojoeiro é um tributo à precisão e ao mistério do tempo. Relógios de parede de diferentes épocas, engrenagens expostas na decoração, e uma bancada decorativa com ferramentas de relojoeiro. A vista para o jardim interno traz paz, enquanto os detalhes steampunk aguçam a imaginação.',
                'descricao_curta': 'Relógios de parede, engrenagens expostas e vista para o jardim.',
                'capacidade': 2, 'metragem': 28, 'preco_base': 380,
                'status': 'disponivel', 'destaque': True, 'nota_avaliacao': 4.8, 'ordem': 2,
                'cor': MUSGO,
            },
            {
                'nome': 'Torre do Astrônomo',
                'categoria': categorias['Chalé Família'],
                'descricao': 'A Torre do Astrônomo é o sonho de qualquer família aventureira. Com dois andares, o térreo abriga a sala com lareira e o andar superior tem a claraboia com vista para as estrelas. Telescópio decorativo, mapas celestes nas paredes e uma atmosfera que convida a olhar para cima e sonhar.',
                'descricao_curta': 'Dois andares, claraboia com vista para as estrelas e lareira.',
                'capacidade': 4, 'metragem': 55, 'preco_base': 650,
                'status': 'disponivel', 'destaque': True, 'nota_avaliacao': 5.0, 'ordem': 3,
                'cor': MADEIRA,
            },
            {
                'nome': 'Estúdio da Cartógrafa',
                'categoria': categorias['Suíte Temática'],
                'descricao': 'O Estúdio da Cartógrafa é um refúgio para casais que amam explorar. Mapas antigos emolduram as paredes, uma mesa de luz serve como mesa de cabeceira e a decoração remete aos grandes exploradores. Cama king size com roupa de cama em tons terrosos.',
                'descricao_curta': 'Mapas antigos, mesa de luz e atmosfera de explorador.',
                'capacidade': 2, 'metragem': 30, 'preco_base': 420,
                'status': 'disponivel', 'destaque': False, 'nota_avaliacao': 4.7, 'ordem': 4,
                'cor': MUSGO,
            },
            {
                'nome': 'Ateliê do Ferreiro',
                'categoria': categorias['Standard'],
                'descricao': 'O Ateliê do Ferreiro é a essência do rústico steampunk. Cabeceira em ferro forjado, luminárias feitas com peças de engrenagens reais e paredes de tijolo aparente. Compacto mas acolhedor, é ideal para viajantes solo ou casais que valorizam autenticidade.',
                'descricao_curta': 'Ferro forjado, engrenagens reais e tijolo aparente.',
                'capacidade': 2, 'metragem': 22, 'preco_base': 290,
                'status': 'disponivel', 'destaque': False, 'nota_avaliacao': 4.6, 'ordem': 5,
                'cor': MADEIRA,
            },
            {
                'nome': 'Vagão do Maquinista',
                'categoria': categorias['Suíte Premium'],
                'descricao': 'O Vagão do Maquinista reproduz o interior de um vagão de trem de luxo do século XIX. Painéis de madeira entalhada, janelas arredondadas com cortinas de veludo e iluminação a gás simulada. Inclui banheira vitoriana e mini bar com cristaleira.',
                'descricao_curta': 'Interior de vagão de trem vitoriano com banheira e mini bar.',
                'capacidade': 2, 'metragem': 38, 'preco_base': 520,
                'status': 'disponivel', 'destaque': False, 'nota_avaliacao': 4.9, 'ordem': 6,
                'cor': NOTURNO,
            },
        ]

        for q in quartos_data:
            cor = q.pop('cor')
            obj, created = Quarto.objects.get_or_create(nome=q['nome'], defaults=q)
            if created:
                # Foto principal
                buf = gerar_imagem(800, 600, q['nome'], cor)
                obj.foto_principal.save(f'{obj.nome.lower().replace(" ", "_")}.jpg', ContentFile(buf.read()))

                # 3 fotos extras
                extras = ['Vista', 'Detalhe', 'Banheiro']
                for i, label in enumerate(extras):
                    buf = gerar_imagem(800, 600, f'{q["nome"]}\n{label}', cor)
                    FotoQuarto.objects.create(
                        quarto=obj,
                        legenda=f'{label} — {q["nome"]}',
                        ordem=i,
                        imagem=ContentFile(buf.read(), name=f'{obj.nome.lower().replace(" ", "_")}_{label.lower()}.jpg'),
                    )

        self.stdout.write(f'  Quartos: {Quarto.objects.count()} (com fotos)')

        # ==========================================
        # TEMPORADAS
        # ==========================================
        temporadas_data = [
            {'nome': 'Baixa Temporada 2026', 'tipo': 'baixa', 'data_inicio': date(2026, 3, 1), 'data_fim': date(2026, 6, 14), 'multiplicador': 0.85},
            {'nome': 'Férias de Julho 2026', 'tipo': 'alta', 'data_inicio': date(2026, 7, 1), 'data_fim': date(2026, 7, 31), 'multiplicador': 1.40},
            {'nome': 'Alta Temporada Verão 2026/27', 'tipo': 'alta', 'data_inicio': date(2026, 12, 15), 'data_fim': date(2027, 2, 28), 'multiplicador': 1.50},
            {'nome': 'Réveillon 2026', 'tipo': 'feriado', 'data_inicio': date(2026, 12, 28), 'data_fim': date(2027, 1, 3), 'multiplicador': 2.00},
            {'nome': 'Carnaval 2027', 'tipo': 'feriado', 'data_inicio': date(2027, 2, 14), 'data_fim': date(2027, 2, 18), 'multiplicador': 1.80},
        ]
        for t in temporadas_data:
            Temporada.objects.get_or_create(nome=t['nome'], defaults=t)
        self.stdout.write(f'  Temporadas: {Temporada.objects.count()}')

        # ==========================================
        # HÓSPEDES
        # ==========================================
        hospedes_data = [
            {'nome': 'Maria Clara Oliveira', 'email': 'maria.clara@email.com', 'telefone': '(49) 99901-1234', 'cpf': '123.456.789-00'},
            {'nome': 'Rafael Santos Costa', 'email': 'rafael.santos@email.com', 'telefone': '(48) 99802-5678', 'cpf': '234.567.890-11'},
            {'nome': 'Ana Luísa Ferreira', 'email': 'ana.luisa@email.com', 'telefone': '(47) 99703-9012', 'cpf': '345.678.901-22'},
            {'nome': 'João Pedro Martins', 'email': 'joao.pedro@email.com', 'telefone': '(11) 99604-3456', 'cpf': '456.789.012-33'},
            {'nome': 'Camila Rocha Lima', 'email': 'camila.rocha@email.com', 'telefone': '(21) 99505-7890', 'cpf': '567.890.123-44'},
            {'nome': 'Lucas Almeida Silva', 'email': 'lucas.almeida@email.com', 'telefone': '(31) 99406-2345', 'cpf': '678.901.234-55'},
            {'nome': 'Beatriz Souza Mendes', 'email': 'beatriz.souza@email.com', 'telefone': '(41) 99307-6789', 'cpf': '789.012.345-66'},
            {'nome': 'Fernando Dias Ribeiro', 'email': 'fernando.dias@email.com', 'telefone': '(51) 99208-0123', 'cpf': '890.123.456-77'},
        ]
        for h in hospedes_data:
            Hospede.objects.get_or_create(email=h['email'], defaults=h)
        self.stdout.write(f'  Hóspedes: {Hospede.objects.count()}')

        # ==========================================
        # EXPERIÊNCIAS
        # ==========================================
        experiencias_data = [
            {'nome': 'Trilha do Inventor', 'descricao': 'Caminhada guiada pelas invenções do Vô Testa espalhadas pela propriedade. Cada parada revela uma história.', 'ordem': 1,
             'icone': 'M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z'},
            {'nome': 'Passeio de Barco', 'descricao': 'Navegue pelo lago ao pôr do sol com vista para as montanhas e a pousada iluminada.', 'ordem': 2,
             'icone': 'M20.893 13.393l-1.135-1.135a2.252 2.252 0 01-.421-.585l-1.08-2.16'},
            {'nome': 'Fogueira & Estrelas', 'descricao': 'Noites ao ar livre com fogueira, música acústica e o céu mais estrelado que você já viu.', 'ordem': 3,
             'icone': 'M15.362 5.214A8.252 8.252 0 0112 21 8.25 8.25 0 016.038 7.048'},
            {'nome': 'Gastronomia Colonial', 'descricao': 'Café colonial com receitas da família e ingredientes colhidos da nossa horta.', 'ordem': 4,
             'icone': 'M12 8.25v-1.5m0 1.5c-1.355 0-2.697.056-4.024.166C6.845 8.51 6 9.473 6 10.608v2.513'},
            {'nome': 'Oficina Steampunk', 'descricao': 'Workshop de artesanato com materiais reciclados, no espírito inventivo do Vô Testa.', 'ordem': 5,
             'icone': 'M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245'},
            {'nome': 'Spa & Bem-estar', 'descricao': 'Massagens, sauna e piscina aquecida com vista para a natureza intocada.', 'ordem': 6,
             'icone': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733'},
        ]
        for e in experiencias_data:
            Experiencia.objects.get_or_create(nome=e['nome'], defaults=e)
        self.stdout.write(f'  Experiências: {Experiencia.objects.count()}')

        # ==========================================
        # DEPOIMENTOS
        # ==========================================
        depoimentos_data = [
            {'nome_hospede': 'Maria Clara', 'texto': 'Um lugar fora do tempo. A roda d\'água é hipnotizante, os quartos são incríveis e o café colonial é o melhor que já provei. Marcou nossa vida para sempre.', 'nota': 5, 'plataforma': 'booking', 'data_avaliacao': date(2026, 3, 15), 'ordem': 1},
            {'nome_hospede': 'Rafael Santos', 'texto': 'Levei a família toda e cada um encontrou seu canto favorito. As crianças não queriam ir embora da Oficina Steampunk. Foi realmente muito especial.', 'nota': 5, 'plataforma': 'google', 'data_avaliacao': date(2026, 4, 22), 'ordem': 2},
            {'nome_hospede': 'Ana Luísa', 'texto': 'Gostaria de agradecer todo o cuidado que vocês tiveram. O passeio de barco ao pôr do sol foi inesquecível. Voltaremos com certeza!', 'nota': 5, 'plataforma': 'tripadvisor', 'data_avaliacao': date(2026, 5, 10), 'ordem': 3},
            {'nome_hospede': 'João Pedro', 'texto': 'A Cabine do Navegador superou todas as expectativas. Acordar com a vista do lago e o som da natureza foi transformador. Melhor viagem da minha vida.', 'nota': 5, 'plataforma': 'booking', 'data_avaliacao': date(2026, 4, 5), 'ordem': 4},
            {'nome_hospede': 'Camila Rocha', 'texto': 'Fui para descansar e voltei renovada. O spa é maravilhoso, a comida é divina e a equipe trata todo mundo como família. Nota 1000!', 'nota': 5, 'plataforma': 'google', 'data_avaliacao': date(2026, 5, 1), 'ordem': 5},
            {'nome_hospede': 'Fernando Dias', 'texto': 'Lugar incrível para quem gosta de história e natureza. Cada cantinho da pousada conta uma história. A trilha do inventor é imperdível.', 'nota': 4, 'plataforma': 'tripadvisor', 'data_avaliacao': date(2026, 3, 28), 'ordem': 6},
        ]
        for d in depoimentos_data:
            Depoimento.objects.get_or_create(nome_hospede=d['nome_hospede'], plataforma=d['plataforma'], defaults=d)
        self.stdout.write(f'  Depoimentos: {Depoimento.objects.count()}')

        # ==========================================
        # GALERIA
        # ==========================================
        galeria_data = [
            {'legenda': 'Roda d\'Água Original', 'categoria': 'pousada', 'destaque': True, 'cor': MADEIRA},
            {'legenda': 'Vista do Lago ao Entardecer', 'categoria': 'natureza', 'destaque': False, 'cor': NOTURNO},
            {'legenda': 'Cabine do Navegador', 'categoria': 'quartos', 'destaque': False, 'cor': MUSGO},
            {'legenda': 'Pôr do Sol nas Montanhas', 'categoria': 'natureza', 'destaque': True, 'cor': MADEIRA},
            {'legenda': 'Café Colonial', 'categoria': 'gastronomia', 'destaque': False, 'cor': LAMPIAO},
            {'legenda': 'Fogueira à Noite', 'categoria': 'experiencias', 'destaque': False, 'cor': NOTURNO},
            {'legenda': 'Trilha do Inventor', 'categoria': 'experiencias', 'destaque': False, 'cor': MUSGO},
            {'legenda': 'Fachada da Pousada', 'categoria': 'pousada', 'destaque': True, 'cor': MADEIRA},
            {'legenda': 'Oficina Steampunk', 'categoria': 'experiencias', 'destaque': False, 'cor': NOTURNO},
            {'legenda': 'Passeio de Barco', 'categoria': 'experiencias', 'destaque': False, 'cor': MUSGO},
            {'legenda': 'Jardim Interno', 'categoria': 'natureza', 'destaque': False, 'cor': MUSGO},
            {'legenda': 'Engrenagens Decorativas', 'categoria': 'pousada', 'destaque': False, 'cor': LAMPIAO},
        ]
        for i, g in enumerate(galeria_data):
            cor = g.pop('cor')
            if not FotoGaleria.objects.filter(legenda=g['legenda']).exists():
                tamanho = (1200, 800) if g['destaque'] else (800, 800)
                buf = gerar_imagem(tamanho[0], tamanho[1], g['legenda'], cor)
                FotoGaleria.objects.create(
                    legenda=g['legenda'],
                    categoria=g['categoria'],
                    destaque=g['destaque'],
                    ordem=i,
                    imagem=ContentFile(buf.read(), name=f'galeria_{i:02d}.jpg'),
                )
        self.stdout.write(f'  Galeria: {FotoGaleria.objects.count()} fotos')

        # ==========================================
        # CONFIGURAÇÃO DO SITE
        # ==========================================
        ConfiguracaoSite.load()
        self.stdout.write('  Configuração do Site: OK')

        self.stdout.write(self.style.SUCCESS('\nDados fictícios populados com sucesso!'))
