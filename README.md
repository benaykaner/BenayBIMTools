# BenayBIMTools
Revit productivity tools developed by Benay Kaner for pyRevit.
BenayBIMTools

BenayBIMTools, Autodesk Revit içerisindeki tekrarlayan işlemleri hızlandırmak amacıyla pyRevit üzerinde geliştirilmiş bir Revit otomasyon araç setidir.

Geliştirici: Benay Kaner

Mevcut Araçlar
Interior Auto Dimension
Exterior Auto Dimension
Grid Dimension

BenayBIMTools şu anda Beta sürümündedir. Otomatik oluşturulan ölçüler proje tesliminden önce kullanıcı tarafından kontrol edilmelidir.

Gereksinimler

BenayBIMTools'u kullanabilmek için bilgisayarınızda aşağıdakilerin kurulu olması gerekir:

Autodesk Revit
pyRevit
Windows işletim sistemi

BenayBIMTools bağımsız bir Revit Add-in değildir. Araçlar pyRevit üzerinden çalışır.

Kurulum
1. pyRevit'i Kurun

Bilgisayarınızda pyRevit kurulu değilse öncelikle pyRevit'i kurun.

Kurulum tamamlandıktan sonra Revit'i açın ve üst menüde pyRevit sekmesinin göründüğünü kontrol edin.

pyRevit sekmesi görünüyorsa BenayBIMTools kurulumuna devam edebilirsiniz.

2. BenayBIMTools'u İndirin

GitHub sayfasındaki Releases bölümüne girin.

En güncel sürümü açın ve BenayBIMTools.zip dosyasını indirin.

3. ZIP Dosyasını Çıkarın

İndirdiğiniz BenayBIMTools.zip dosyasını bilgisayarınızda istediğiniz bir klasöre çıkarın.

Önerilen örnek klasör:

C:\Users\Kullanici\Documents\BIMworkflow

ZIP çıkarıldıktan sonra klasör yapısı şu şekilde olmalıdır:

BIMworkflow
└── BenayBIMTools.extension
  ├── BenayBIMTools.tab
  ├── lib
  ├── dist
  └── LICENSE

Önemli:

BenayBIMTools.extension klasörü başka bir BenayBIMTools.extension klasörünün içinde olmamalıdır.

Yanlış yapı:

BIMworkflow
└── BenayBIMTools.extension
  └── BenayBIMTools.extension
    └── BenayBIMTools.tab

Doğru yapı:

BIMworkflow
└── BenayBIMTools.extension
  ├── BenayBIMTools.tab
  ├── lib
  └── diğer dosyalar

pyRevit'e BenayBIMTools Ekleme
4. Revit'i Açın

Autodesk Revit'i açın.

Üst menüden:

pyRevit > Settings

bölümüne girin.

5. Custom Extension Directories Bölümünü Açın

pyRevit Settings penceresinde Custom Extension Directories bölümünü bulun.

Add folder butonuna tıklayın.

6. Doğru Klasörü Seçin

Burada dikkat edilmesi gereken en önemli nokta şudur:

BenayBIMTools.extension klasörünün kendisini seçmeyin.

BenayBIMTools.extension klasörünü içinde bulunduran üst klasörü seçin.

Örneğin klasör yapınız şu şekildeyse:

C:\Users\Kullanici\Documents\BIMworkflow
└── BenayBIMTools.extension

pyRevit içerisinde seçmeniz gereken klasör:

C:\Users\Kullanici\Documents\BIMworkflow

olmalıdır.

Yani:

BIMworkflow ← BUNU SEÇİN
└── BenayBIMTools.extension
  └── BenayBIMTools.tab

BenayBIMTools.extension klasörünü doğrudan seçmeyin.

Temel kural:

Custom Extension Directory olarak seçtiğiniz klasörün hemen altında BenayBIMTools.extension klasörü bulunmalıdır.

7. Ayarları Kaydedin

Doğru klasörü ekledikten sonra pyRevit Settings penceresinin altındaki:

Save Settings and Reload

butonuna basın.

Birkaç saniye sonra Revit üst menüsünde:

BenayBIMTools

sekmesi görünmelidir.

BenayBIMTools Sekmesi Görünmüyorsa

Öncelikle pyRevit Settings içerisinde eklediğiniz klasörü kontrol edin.

Doğru yapı:

SEÇTİĞİNİZ KLASÖR
└── BenayBIMTools.extension
  └── BenayBIMTools.tab

Örneğin:

C:\Users\Kullanici\Documents\BIMworkflow
└── BenayBIMTools.extension

ise Custom Extension Directory olarak:

C:\Users\Kullanici\Documents\BIMworkflow

eklenmelidir.

Save Settings and Reload işleminden sonra sekme hâlâ görünmüyorsa Revit'i tamamen kapatıp yeniden açın.

Kullanım

Kurulum tamamlandıktan sonra Revit Ribbon üzerinde BenayBIMTools sekmesine girin.

Buradan kullanmak istediğiniz aracı seçebilirsiniz.

Mevcut araçlar:

Interior Auto Dimension
Exterior Auto Dimension
Grid Dimension

Araçlar aktif Revit görünüşü ve mevcut model elemanları üzerinden çalışır.

Interior Auto Dimension

Interior Auto Dimension aracı, Revit plan görünüşlerinde iç ölçülendirme sürecini otomatikleştirmek amacıyla geliştirilmiştir.

Araç proje geometrisini ve uygun Revit referanslarını analiz ederek ölçü zincirleri oluşturmaya çalışır.

Model geometrisi, duvar birleşimleri, kapı ve pencere familyaları, kolonlar ve farklı proje koşulları sonuçları etkileyebilir.

Bu nedenle oluşturulan ölçüler kullanıcı tarafından kontrol edilmelidir.

Exterior Auto Dimension

Exterior Auto Dimension aracı dış ölçülendirme sürecini hızlandırmak amacıyla geliştirilmiştir.

Oluşturulan ölçülerin proje dokümantasyonunda kullanılmadan önce kontrol edilmesi önerilir.

Grid Dimension

Grid Dimension aracı Revit akslarının ölçülendirilmesini hızlandırmak amacıyla geliştirilmiştir.

Beta Sürümü Hakkında

BenayBIMTools aktif olarak geliştirilmektedir.

Bu sürüm Beta sürümüdür.

Farklı Revit projelerinde aşağıdaki durumlar farklı sonuçlar oluşturabilir:

Farklı duvar birleşimleri
Farklı Wall Type yapıları
Kapı ve pencere familyaları
Kolon geometrileri
Karmaşık mahal geometrileri
Farklı modelleme yöntemleri
Farklı Revit sürümleri

BenayBIMTools kullanıcıya zaman kazandırmayı amaçlayan bir otomasyon aracıdır.

Oluşturulan ölçülerin ve diğer çıktıların doğruluğunun son kontrolü kullanıcıya aittir.

Hata Bildirimi ve Geri Bildirim

Bir araç beklenmeyen sonuç oluşturursa geri bildirim gönderirken mümkünse aşağıdaki bilgileri paylaşın:

Kullanılan Revit sürümü
Kullanılan pyRevit sürümü
Kullanılan BenayBIMTools aracı
Hatanın veya beklenmeyen sonucun ekran görüntüsü
Sorunun hangi işlem sırasında oluştuğu

GitHub repository içerisindeki Issues bölümünden hata bildirimi yapılabilir.

Güncelleme

Yeni bir BenayBIMTools sürümü yayınlandığında GitHub üzerindeki Releases bölümünden en güncel BenayBIMTools.zip dosyasını indirebilirsiniz.

Eski BenayBIMTools.extension klasörünüzü kaldırdıktan sonra yeni sürümdeki klasörü aynı konuma yerleştirin.

Ardından Revit içerisinde pyRevit > Reload işlemini uygulayın.

Gerekirse Revit'i kapatıp tekrar açın.

License

Copyright © 2026 Benay Kaner.

All Rights Reserved.

BenayBIMTools yalnızca kullanım amacıyla indirilebilir ve kullanılabilir.

İzin alınmadan aşağıdaki işlemler yapılamaz:

Kaynak kodunun değiştirilmesi
Yazılımın veya kaynak kodunun yeniden dağıtılması
Başka platformlarda yeniden yayınlanması
Satılması
Ticari olarak yeniden dağıtılması
Başka bir yazılıma veya ürüne dahil edilmesi
Yazılımın veya kodun başka bir kişi tarafından kendi çalışması gibi sunulması

Detaylı kullanım koşulları için repository içerisindeki LICENSE dosyasını inceleyin.

Developer

Benay Kaner

BenayBIMTools
Revit Workflow Automation
